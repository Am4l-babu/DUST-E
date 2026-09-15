"""
scenario.py - scripted people walking past a camera that does not exist.

Actors follow keyframes of (time, distance, bearing, visible). Each simulated
frame projects them through the same camera geometry the real pipeline
inverts, adds seeded box jitter, and gives each actor a torso signature from a
patch of its shirt colour. The output is a list of Detections per frame -
exactly what the real detector plus appearance stage produce - so the tracker
and world model under test are the production code, unmodified.

Everything is driven by binbrain.prng, so a scenario is bit-for-bit
repeatable: a failing test fails the same way every time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

import numpy as np

from ..config import BrainConfig
from ..prng import Prng
from ..vision.appearance import signature_from_pixels
from ..vision.geometry import box_for_standing_object
from ..vision.types import BBox, Detection


@dataclass(frozen=True)
class Keyframe:
    t: float
    distance_m: float
    bearing_deg: float
    visible: bool = True        # False from this keyframe until the next one


@dataclass(frozen=True)
class Actor:
    name: str
    keyframes: tuple[Keyframe, ...]
    label: str = "person"
    color_bgr: tuple[int, int, int] = (40, 40, 200)
    height_m: float = 1.70
    width_m: float = 0.45
    score: float = 0.80

    def state_at(self, t: float) -> tuple[float, float] | None:
        """(distance, bearing) at time t, or None if not in the scene."""
        ks = self.keyframes
        if not ks or t < ks[0].t:
            return None
        for a, b in zip(ks, ks[1:]):
            if a.t <= t < b.t:
                if not a.visible:
                    return None
                f = (t - a.t) / (b.t - a.t)
                return (a.distance_m + f * (b.distance_m - a.distance_m),
                        a.bearing_deg + f * (b.bearing_deg - a.bearing_deg))
        last = ks[-1]
        return (last.distance_m, last.bearing_deg) if last.visible else None


@dataclass(frozen=True)
class SimFrame:
    t: float
    detections: list[Detection]
    ego_forward_mps: float


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    actors: tuple[Actor, ...]
    duration_s: float
    fps: float = 5.0
    jitter: float = 0.003          # normalised box-edge noise
    seed: int = 1
    ego_forward_mps: float = 0.0   # constant robot speed toward the scene

    def frames(self, cfg: BrainConfig) -> Iterator[SimFrame]:
        rng = Prng(self.seed)
        n = int(round(self.duration_s * self.fps))
        for i in range(n + 1):
            t = i / self.fps
            detections: list[Detection] = []
            for actor in self.actors:
                state = actor.state_at(t)
                if state is None:
                    continue
                box = box_for_standing_object(state[0], state[1], actor.height_m, actor.width_m,
                                              cfg.camera, cfg.geometry)
                if box is None:
                    continue
                box = _jitter(box, self.jitter, rng)
                if box.w <= 0.0 or box.h <= 0.0:
                    continue
                signature = _shirt_signature(actor.color_bgr, rng) if actor.label == "person" else None
                detections.append(Detection(actor.label, actor.score, box, signature))
            yield SimFrame(t, detections, self.ego_forward_mps)


def _jitter(box: BBox, amount: float, rng: Prng) -> BBox:
    if amount <= 0.0:
        return box
    j = lambda: rng.uniform(-amount, amount)  # noqa: E731
    # A detector's box edge never extends past the frame, and one already cut
    # off by the frame stays cut off; noise must not invent truncation either.
    def edge(v: float) -> float:
        return v if v <= 0.0 or v >= 1.0 else min(0.999, max(0.001, v + j()))
    return BBox(edge(box.x1), edge(box.y1), edge(box.x2), edge(box.y2))


def _shirt_signature(color_bgr: tuple[int, int, int], rng: Prng) -> np.ndarray | None:
    patch = np.empty((8, 8, 3), dtype=np.uint8)
    for y in range(8):
        for x in range(8):
            for c in range(3):
                patch[y, x, c] = max(0, min(255, color_bgr[c] + rng.range(-18, 18)))
    return signature_from_pixels(patch)


# ---------------------------------------------------------------------------
# Built-in scenarios
# ---------------------------------------------------------------------------
RED = (40, 40, 200)
BLUE = (200, 60, 30)
GREEN = (50, 170, 40)


def walk_in() -> Scenario:
    """Scene 2-7 of the demo: someone arrives, stops to talk, and leaves."""
    return Scenario(
        "walk_in", "one person walks up, stands and talks, walks away and out of view",
        (Actor("alice", (
            Keyframe(0.0, 5.0, 20.0),
            Keyframe(6.0, 1.3, 0.0),
            Keyframe(10.0, 1.3, 0.0),
            Keyframe(15.0, 4.5, -10.0),
            Keyframe(15.2, 4.5, -10.0, visible=False),
        ), color_bgr=RED),),
        duration_s=20.0)


def flicker() -> Scenario:
    """A detector that drops someone for a moment must not create a second person."""
    return Scenario(
        "flicker", "one person stands still at 2.5 m; the detector misses them twice",
        (Actor("bob", (
            Keyframe(0.0, 2.5, 5.0),
            Keyframe(3.0, 2.5, 5.0, visible=False),
            Keyframe(3.6, 2.5, 5.0),
            Keyframe(6.0, 2.5, 5.0, visible=False),
            Keyframe(6.4, 2.5, 5.0),
            Keyframe(10.0, 2.5, 5.0),
        ), color_bgr=GREEN),),
        duration_s=10.0)


def returning() -> Scenario:
    """The "you again?" moment."""
    return Scenario(
        "returning", "a person leaves the frame for 12 s and comes back",
        (Actor("carol", (
            Keyframe(0.0, 3.0, 0.0),
            Keyframe(4.0, 3.0, 0.0, visible=False),
            Keyframe(16.0, 3.5, 25.0),
            Keyframe(22.0, 2.0, 0.0),
        ), color_bgr=BLUE),),
        duration_s=22.0)


def two_people_swap() -> Scenario:
    """Two people leave and return in the opposite order and opposite positions.

    Only appearance can keep their identities straight.
    """
    return Scenario(
        "two_people_swap", "red and blue both leave, then return on each other's side",
        (
            Actor("red", (
                Keyframe(0.0, 3.0, -20.0),
                Keyframe(4.0, 3.0, -20.0, visible=False),
                Keyframe(12.0, 3.0, 20.0),
                Keyframe(18.0, 3.0, 20.0),
            ), color_bgr=RED),
            Actor("blue", (
                Keyframe(0.0, 3.2, 20.0),
                Keyframe(4.0, 3.2, 20.0, visible=False),
                Keyframe(10.0, 3.2, -20.0),
                Keyframe(18.0, 3.2, -20.0),
            ), color_bgr=BLUE),
        ),
        duration_s=18.0)


def robot_drives_to_statue() -> Scenario:
    """The robot drives at 0.3 m/s toward someone standing perfectly still."""
    return Scenario(
        "robot_drives_to_statue", "range shrinks only because the robot is moving",
        (Actor("statue", (
            Keyframe(0.0, 4.0, 0.0),
            Keyframe(6.0, 2.2, 0.0),
        ), color_bgr=GREEN),),
        duration_s=6.0, ego_forward_mps=0.3)


def person_with_cup() -> Scenario:
    return Scenario(
        "person_with_cup", "a person stands near a cup; the cup is news once",
        (
            Actor("dave", (Keyframe(0.0, 2.8, -10.0), Keyframe(12.0, 2.8, -10.0)), color_bgr=RED),
            Actor("cup", (Keyframe(1.0, 2.0, 15.0), Keyframe(12.0, 2.0, 15.0)),
                  label="cup", height_m=0.12, width_m=0.09, score=0.6),
        ),
        duration_s=12.0)


SCENARIOS: dict[str, Callable[[], Scenario]] = {
    "walk_in": walk_in,
    "flicker": flicker,
    "returning": returning,
    "two_people_swap": two_people_swap,
    "robot_drives_to_statue": robot_drives_to_statue,
    "person_with_cup": person_with_cup,
}
