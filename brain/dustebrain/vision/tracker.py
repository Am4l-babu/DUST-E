"""
tracker.py - turning detections into things that persist.

A detector says "there is a person in this frame". The robot needs "that is
the same person as a moment ago, they are 1.8 m away and walking toward me".

Association is greedy: overlap (IoU) first, centre distance as a fallback for
fast movers and low frame rates, same label only. At ~5 Hz on a slow CPU this
is as good as anything heavier, and it is trivially debuggable.

Lifecycle:

    TENTATIVE --confirm_hits--> CONFIRMED --lost_after_s unseen--> LOST
        |                           ^                                |
        '--lost_after_s unseen--> deleted     revived on re-match ---'
                                                   forget_after_s --> deleted

Only CONFIRMED tracks are "visible" to anything downstream, so a single
false-positive frame never becomes a person the robot says hello to.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

import numpy as np

from ..config import BrainConfig
from . import appearance
from .geometry import bearing_deg, estimate_range
from .types import BBox, Detection


class TrackStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    LOST = "LOST"


@dataclass
class Track:
    track_id: int
    label: str
    box: BBox
    score: float
    first_seen: float
    last_seen: float
    hits: int = 1
    status: TrackStatus = TrackStatus.TENTATIVE
    bearing_deg: float = 0.0
    distance_m: float | None = None
    distance_reliable: bool = False
    distance_method: str = "none"
    distance_upper_m: float | None = None
    radial_velocity_mps: float | None = None      # + = moving away from the camera
    signature: np.ndarray | None = field(default=None, repr=False)
    history: deque = field(default_factory=deque, repr=False)   # (t, raw distance, method)

    @property
    def visible(self) -> bool:
        return self.status is TrackStatus.CONFIRMED


class Tracker:
    def __init__(self, cfg: BrainConfig) -> None:
        self._cfg = cfg
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    @property
    def tracks(self) -> list[Track]:
        return list(self._tracks.values())

    def update(self, detections: Sequence[Detection], t: float) -> list[Track]:
        tc = self._cfg.tracker
        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()

        for track_id, det_index in self._associate(detections, t):
            self._apply(self._tracks[track_id], detections[det_index], t)
            matched_tracks.add(track_id)
            matched_dets.add(det_index)

        for i, det in enumerate(detections):
            if i not in matched_dets:
                self._create(det, t)

        for track_id in list(self._tracks):
            if track_id in matched_tracks:
                continue
            track = self._tracks[track_id]
            age = t - track.last_seen
            if track.status is TrackStatus.TENTATIVE and age > tc.lost_after_s:
                del self._tracks[track_id]
            elif track.status is TrackStatus.CONFIRMED and age > tc.lost_after_s:
                track.status = TrackStatus.LOST
            elif track.status is TrackStatus.LOST and age > tc.forget_after_s:
                del self._tracks[track_id]

        return self.tracks

    # ------------------------------------------------------------------
    def _associate(self, detections: Sequence[Detection], t: float) -> list[tuple[int, int]]:
        tc = self._cfg.tracker
        candidates: list[tuple[float, int, int]] = []
        for track in self._tracks.values():
            for i, det in enumerate(detections):
                if det.label != track.label:
                    continue
                iou = track.box.iou(det.box)
                if iou >= tc.iou_match:
                    cost = 1.0 - iou
                else:
                    dist = track.box.center_distance(det.box)
                    if dist > tc.max_center_jump:
                        continue
                    cost = 1.0 + dist
                if track.status is TrackStatus.LOST:
                    cost += 0.5        # an active track gets first claim
                candidates.append((cost, track.track_id, i))

        candidates.sort()
        used_tracks: set[int] = set()
        used_dets: set[int] = set()
        pairs: list[tuple[int, int]] = []
        for _cost, track_id, i in candidates:
            if track_id in used_tracks or i in used_dets:
                continue
            used_tracks.add(track_id)
            used_dets.add(i)
            pairs.append((track_id, i))
        return pairs

    def _create(self, det: Detection, t: float) -> None:
        track = Track(self._next_id, det.label, det.box, det.score, t, t)
        self._next_id += 1
        self._measure(track, det, t)
        if track.hits >= self._cfg.tracker.confirm_hits:
            track.status = TrackStatus.CONFIRMED
        self._tracks[track.track_id] = track

    def _apply(self, track: Track, det: Detection, t: float) -> None:
        tc = self._cfg.tracker
        if track.status is TrackStatus.LOST:
            # Revived: its old position and motion history describe a
            # different moment and must not be blended into this one.
            track.box = det.box
            track.history.clear()
            track.status = TrackStatus.CONFIRMED
        else:
            track.box = track.box.blend(det.box, tc.box_smoothing)
        track.hits += 1
        track.score = det.score
        track.last_seen = t
        if track.status is TrackStatus.TENTATIVE and track.hits >= tc.confirm_hits:
            track.status = TrackStatus.CONFIRMED
        self._measure(track, det, t)

    def _measure(self, track: Track, det: Detection, t: float) -> None:
        cfg = self._cfg
        tc = cfg.tracker
        track.bearing_deg = bearing_deg(det.box.cx, cfg.camera.hfov_deg)

        if det.signature is not None:
            track.signature = (det.signature if track.signature is None
                               else appearance.blend(track.signature, det.signature))

        if det.label not in cfg.geometry.ranged_labels:
            return

        # Measured from the raw detection, not the smoothed box: whether the
        # box touches the frame edge is a fact about this frame.
        r = estimate_range(det.box, cfg.camera, cfg.geometry)
        track.distance_reliable = r.reliable
        track.distance_upper_m = r.upper_bound_m
        if r.distance_m is None:
            track.distance_m = None
            track.distance_method = "none"
            track.radial_velocity_mps = None
            return

        if track.distance_m is None or r.method != track.distance_method:
            track.distance_m = r.distance_m          # never blend across estimators
        else:
            track.distance_m += tc.distance_smoothing * (r.distance_m - track.distance_m)
        track.distance_method = r.method

        track.history.append((t, r.distance_m, r.method))
        while track.history and t - track.history[0][0] > tc.velocity_window_s:
            track.history.popleft()
        track.radial_velocity_mps = self._radial_velocity(track)

    def _radial_velocity(self, track: Track) -> float | None:
        """Least-squares slope over recent samples from the current estimator.

        Switching from the ground estimate to the width estimate as someone
        walks close is a step change in distance, not motion, so only samples
        from the same estimator count.
        """
        tc = self._cfg.tracker
        method = track.distance_method
        samples = [(ts, d) for ts, d, m in track.history if m == method]
        if len(samples) < tc.min_velocity_samples:
            return None
        ts = np.array([s[0] for s in samples], dtype=np.float64)
        ds = np.array([s[1] for s in samples], dtype=np.float64)
        if ts[-1] - ts[0] < 0.4 * tc.velocity_window_s:
            return None
        tm = ts - ts.mean()
        denom = float((tm * tm).sum())
        if denom <= 1e-9:
            return None
        return float((tm * (ds - ds.mean())).sum() / denom)
