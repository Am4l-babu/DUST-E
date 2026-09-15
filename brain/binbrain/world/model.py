"""
model.py - the world model: people, objects, and which changes are news.

Tracks are frame-level bookkeeping; a Person is what the social layer cares
about. The difference matters exactly where it would embarrass the robot:

  * A detector that drops a person for three frames produces a new track. It
    must not produce a new person, or the robot greets them twice.
  * Someone who walks out and comes back a minute later is a new track and
    the same person. That is PERSON_RETURNED, the "you again?" moment.

So a new confirmed track is matched against people recently out of view -
by appearance when a signature exists, by position when the gap is tiny -
before a new person is created. PERSON_LOST is only announced after
`person_lost_s`, so a blink never becomes a departure. PERSON_RETURNED is only
announced for someone whose loss was actually announced.

Honesty rules (same as the firmware's):
  * A stale camera is VISION_OFFLINE, and the summary says "unknown", never
    "nobody here". People are not declared lost while the camera is down.
  * `looking_at_robot` is None until a face detector exists (phase 6).
  * Distances carry `distance_reliable`, and the summary passes it on.

Nothing in here can move anything. It emits events and answers questions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

import numpy as np

from ..config import BrainConfig, ZonesConfig
from ..events import Event, EventType
from ..vision import appearance
from ..vision.tracker import Track, TrackStatus
from ..vision.types import BBox


class Zone(str, Enum):
    UNKNOWN = "UNKNOWN"
    TOO_CLOSE = "TOO_CLOSE"
    INTERACTION = "INTERACTION"
    APPROACH = "APPROACH"
    NOTICE = "NOTICE"
    FAR = "FAR"


_ZONES_BY_DISTANCE = (Zone.TOO_CLOSE, Zone.INTERACTION, Zone.APPROACH, Zone.NOTICE, Zone.FAR)


class Motion(str, Enum):
    UNKNOWN = "UNKNOWN"
    STATIONARY = "STATIONARY"
    APPROACHING = "APPROACHING"
    WALKING_AWAY = "WALKING_AWAY"


def _raw_zone_index(d: float, zones: ZonesConfig) -> int:
    # TOO_CLOSE is strictly below its bound; every other band includes its upper edge.
    for i, bound in enumerate(zones.bounds):
        if (d < bound) if i == 0 else (d <= bound):
            return i
    return len(zones.bounds)


def classify_zone(d: float | None, current: Zone, zones: ZonesConfig) -> Zone:
    """Distance band with hysteresis.

    The current zone is kept as long as it is still reachable anywhere within
    +/- hysteresis of the measurement, so someone standing on a boundary does
    not make the robot twitch between "approach" and "stop".
    """
    if d is None:
        return current
    lo = _raw_zone_index(d - zones.hysteresis_m, zones)
    hi = _raw_zone_index(d + zones.hysteresis_m, zones)
    if current is not Zone.UNKNOWN and lo <= _ZONES_BY_DISTANCE.index(current) <= hi:
        return current
    return _ZONES_BY_DISTANCE[_raw_zone_index(d, zones)]


@dataclass
class Person:
    person_id: int
    first_seen: float
    last_seen: float
    visit_start: float
    box: BBox
    track_id: int | None = None
    visible: bool = True
    bearing_deg: float = 0.0
    distance_m: float | None = None
    distance_reliable: bool = False
    distance_method: str = "none"
    radial_velocity_mps: float | None = None     # ego-motion compensated, + = moving away
    zone: Zone = Zone.UNKNOWN
    motion: Motion = Motion.UNKNOWN
    returns: int = 0
    signature: np.ndarray | None = field(default=None, repr=False)
    interaction_state: str = "UNKNOWN"          # owned by the social layer (phase 6)
    looking_at_robot: bool | None = None         # unknown until a face detector exists
    lost_announced: bool = False
    leaving_announced: bool = False
    motion_candidate: Motion = Motion.UNKNOWN
    motion_candidate_since: float = 0.0

    def to_dict(self, t: float) -> dict[str, Any]:
        return {
            "person_id": self.person_id,
            "visible": self.visible,
            "position": {"x": round(self.box.cx, 3), "y": round(self.box.cy, 3)},
            "bearing_deg": round(self.bearing_deg, 1),
            "distance_estimate": None if self.distance_m is None else round(self.distance_m, 2),
            "distance_reliable": self.distance_reliable,
            "distance_method": self.distance_method,
            "velocity": None if self.radial_velocity_mps is None else round(self.radial_velocity_mps, 2),
            "zone": self.zone.value,
            "motion": self.motion.value,
            "returns": self.returns,
            "last_seen": round(self.last_seen, 3),
            "seen_for_s": round(t - self.visit_start, 1) if self.visible else 0.0,
            "interaction_state": self.interaction_state,
            "looking_at_robot": self.looking_at_robot,
        }


class WorldModel:
    def __init__(self, cfg: BrainConfig) -> None:
        self._cfg = cfg
        self._people: dict[int, Person] = {}
        self._track_to_person: dict[int, int] = {}
        self._next_person_id = 1
        self._object_last_seen: dict[str, float] = {}
        self._visible_objects: list[str] = []
        self._last_update: float | None = None
        self._vision_online = False

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    @property
    def vision_online(self) -> bool:
        return self._vision_online

    @property
    def people(self) -> list[Person]:
        return list(self._people.values())

    def visible_people(self) -> list[Person]:
        far = float("inf")
        return sorted((p for p in self._people.values() if p.visible),
                      key=lambda p: far if p.distance_m is None else p.distance_m)

    def person(self, person_id: int) -> Person | None:
        return self._people.get(person_id)

    def person_for_track(self, track_id: int) -> Person | None:
        pid = self._track_to_person.get(track_id)
        return self._people.get(pid) if pid is not None else None

    @property
    def visible_objects(self) -> list[str]:
        return list(self._visible_objects)

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------
    def update(self, tracks: Sequence[Track], t: float, ego_forward_mps: float = 0.0) -> list[Event]:
        """Fold one tracker output into the world. ego_forward_mps comes from
        body telemetry (phase 2); without it, a robot driving toward a person
        who is standing still would think they were walking toward it."""
        w = self._cfg.world
        events: list[Event] = []
        if not self._vision_online:
            self._vision_online = True
            events.append(Event(EventType.VISION_ONLINE, t))
        self._last_update = t

        live = {tr.track_id: tr for tr in tracks
                if tr.label == w.person_label and tr.status is TrackStatus.CONFIRMED}

        for person in self._people.values():
            if person.visible and person.track_id not in live:
                person.visible = False
                person.track_id = None

        for track_id in sorted(live):
            track = live[track_id]
            person, is_new = self._person_for(track, t)
            returned = False
            if not person.visible:
                returned = person.lost_announced
                if returned:
                    person.returns += 1
                    person.visit_start = t
                person.visible = True
                person.lost_announced = False
                person.leaving_announced = False
            person.track_id = track_id

            state_events = self._refresh(person, track, t, ego_forward_mps, is_new)
            if is_new:
                events.append(self._person_event(EventType.PERSON_DETECTED, person, t))
            elif returned:
                events.append(self._person_event(EventType.PERSON_RETURNED, person, t,
                                                 returns=person.returns))
            events.extend(state_events)

        for person in self._people.values():
            if (not person.visible and not person.lost_announced
                    and t - person.last_seen >= w.person_lost_s):
                person.lost_announced = True
                events.append(Event(EventType.PERSON_LOST, t, person.person_id, {
                    "last_zone": person.zone.value,
                    "seen_for_s": round(person.last_seen - person.visit_start, 1),
                }))
                person.zone = Zone.UNKNOWN
                person.motion = Motion.UNKNOWN
                person.motion_candidate = Motion.UNKNOWN
                person.radial_velocity_mps = None

        self._forget(t)
        events.extend(self._update_objects(tracks, t))
        return events

    def tick(self, t: float) -> list[Event]:
        """Call when no frame arrived. Turns a silent camera into VISION_OFFLINE."""
        if (self._vision_online and self._last_update is not None
                and t - self._last_update > self._cfg.camera.stale_after_s):
            self._vision_online = False
            # Not "lost": the robot does not know where they went, only that it
            # stopped being able to look. No PERSON_LOST for anyone.
            for person in self._people.values():
                person.visible = False
                person.track_id = None
            self._visible_objects = []
            return [Event(EventType.VISION_OFFLINE, t, data={
                "silent_for_s": round(t - self._last_update, 1)})]
        return []

    # ------------------------------------------------------------------
    def _person_for(self, track: Track, t: float) -> tuple[Person, bool]:
        pid = self._track_to_person.get(track.track_id)
        if pid is not None and pid in self._people:
            return self._people[pid], False

        match = self._reidentify(track, t)
        if match is not None:
            self._track_to_person[track.track_id] = match.person_id
            return match, False

        person = Person(self._next_person_id, t, t, t, track.box)
        self._next_person_id += 1
        self._people[person.person_id] = person
        self._track_to_person[track.track_id] = person.person_id
        return person, True

    def _reidentify(self, track: Track, t: float) -> Person | None:
        w = self._cfg.world
        candidates = [p for p in self._people.values()
                      if not p.visible and t - p.last_seen <= w.return_window_s]
        if not candidates:
            return None

        if track.signature is not None:
            scored = [(appearance.similarity(track.signature, p.signature), p)
                      for p in candidates if p.signature is not None]
            if scored:
                best_sim, best = max(scored, key=lambda s: s[0])
                if best_sim >= w.reid_similarity:
                    return best

        # No appearance evidence: only a very recent disappearance close by
        # is the same person. Anything looser merges strangers.
        near = [(p.box.center_distance(track.box), p) for p in candidates
                if t - p.last_seen <= w.reassociate_s
                and p.box.center_distance(track.box) <= w.reassociate_center_dist]
        if near:
            return min(near, key=lambda s: s[0])[1]
        return None

    def _refresh(self, person: Person, track: Track, t: float,
                 ego_forward_mps: float, is_new: bool) -> list[Event]:
        w = self._cfg.world
        events: list[Event] = []

        person.last_seen = track.last_seen
        person.box = track.box
        person.bearing_deg = track.bearing_deg
        person.distance_m = track.distance_m
        person.distance_reliable = track.distance_reliable
        person.distance_method = track.distance_method
        if track.signature is not None:
            person.signature = (track.signature.copy() if person.signature is None
                                else appearance.blend(person.signature, track.signature))

        if track.radial_velocity_mps is not None:
            # Driving toward someone shrinks the range at ego * cos(bearing).
            # Add it back so only the person's own motion remains.
            person.radial_velocity_mps = (track.radial_velocity_mps
                                          + ego_forward_mps * math.cos(math.radians(track.bearing_deg)))

        zone = classify_zone(person.distance_m, person.zone, w.zones)
        if zone is not person.zone:
            previous = person.zone
            person.zone = zone
            if previous is not Zone.UNKNOWN and not is_new:
                events.append(self._person_event(EventType.PERSON_ZONE_CHANGED, person, t,
                                                 previous=previous.value))

        events.extend(self._update_motion(person, t))

        if (person.motion is Motion.WALKING_AWAY and not person.leaving_announced
                and person.distance_m is not None and person.distance_m > w.zones.notice_max_m):
            person.leaving_announced = True
            events.append(self._person_event(EventType.PERSON_LEAVING, person, t))
        elif person.motion is Motion.APPROACHING:
            person.leaving_announced = False
        return events

    def _update_motion(self, person: Person, t: float) -> list[Event]:
        w = self._cfg.world
        v = person.radial_velocity_mps
        if v is None:
            return []
        if v <= -w.approach_speed_mps:
            candidate = Motion.APPROACHING
        elif v >= w.leave_speed_mps:
            candidate = Motion.WALKING_AWAY
        elif abs(v) <= w.stationary_speed_mps:
            candidate = Motion.STATIONARY
        else:
            candidate = person.motion          # deadband: no change of opinion

        if candidate is not person.motion_candidate:
            person.motion_candidate = candidate
            person.motion_candidate_since = t
        if (candidate is person.motion
                or t - person.motion_candidate_since < w.motion_confirm_s):
            return []

        person.motion = candidate
        if candidate is Motion.APPROACHING:
            return [self._person_event(EventType.PERSON_APPROACHING, person, t)]
        if candidate is Motion.WALKING_AWAY:
            return [self._person_event(EventType.PERSON_WALKING_AWAY, person, t)]
        return []

    def _forget(self, t: float) -> None:
        window = self._cfg.world.return_window_s
        stale = [pid for pid, p in self._people.items()
                 if not p.visible and t - p.last_seen > window]
        for pid in stale:
            del self._people[pid]
        if stale:
            gone = set(stale)
            self._track_to_person = {tid: pid for tid, pid in self._track_to_person.items()
                                     if pid not in gone}

    def _update_objects(self, tracks: Sequence[Track], t: float) -> list[Event]:
        w = self._cfg.world
        visible = sorted({tr.label for tr in tracks
                          if tr.label != w.person_label and tr.status is TrackStatus.CONFIRMED})
        self._visible_objects = visible
        events: list[Event] = []
        for label in visible:
            last = self._object_last_seen.get(label)
            if last is None or t - last > w.object_memory_s:
                events.append(Event(EventType.OBJECT_DETECTED, t, data={"label": label}))
            self._object_last_seen[label] = t
        return events

    def _person_event(self, kind: EventType, person: Person, t: float, **extra: Any) -> Event:
        data: dict[str, Any] = {
            "distance_m": None if person.distance_m is None else round(person.distance_m, 2),
            "distance_reliable": person.distance_reliable,
            "direction": self._direction(person.bearing_deg),
            "zone": person.zone.value,
            "motion": person.motion.value,
        }
        data.update(extra)
        return Event(kind, t, person.person_id, data)

    def _direction(self, bearing: float) -> str:
        ahead = self._cfg.world.ahead_deg
        if bearing < -ahead:
            return "left"
        if bearing > ahead:
            return "right"
        return "ahead"

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------
    def summary(self, t: float) -> dict[str, Any]:
        """The compact, honest view an LLM gets. Not raw sensor data."""
        if not self._vision_online:
            return {
                "vision": "offline",
                "people": None,
                "objects": None,
                "note": "Camera unavailable. Do not guess who is present.",
            }
        people = []
        for p in self.visible_people():
            people.append({
                "id": p.person_id,
                "distance_m": None if p.distance_m is None else round(p.distance_m, 1),
                "distance_reliable": p.distance_reliable,
                "direction": self._direction(p.bearing_deg),
                "zone": p.zone.value,
                "motion": p.motion.value,
                "returning_visitor": p.returns > 0,
                "seen_for_s": int(t - p.visit_start),
            })
        return {
            "vision": "online",
            "people_visible": len(people),
            "people": people,
            "objects": self.visible_objects,
        }

    def snapshot(self, t: float) -> dict[str, Any]:
        """Everything, for the dashboard and for debugging."""
        return {
            "t": round(t, 3),
            "vision_online": self._vision_online,
            "people": [p.to_dict(t) for p in sorted(self._people.values(), key=lambda p: p.person_id)],
            "objects": self.visible_objects,
        }
