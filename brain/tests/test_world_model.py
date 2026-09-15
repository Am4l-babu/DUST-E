"""
The acceptance tests for phase 1, run against scripted scenarios instead of a
camera. Each one guards a specific way a social robot embarrasses itself.
"""

import pytest

from binbrain.config import load_config
from binbrain.events import EventType
from binbrain.sim.scenario import (
    flicker,
    person_with_cup,
    returning,
    robot_drives_to_statue,
    two_people_swap,
    walk_in,
)
from binbrain.world.model import Motion, WorldModel, Zone, classify_zone

from .conftest import run_scenario, types_of


def test_walk_in_tells_the_whole_story_once_and_in_order(cfg):
    _, events = run_scenario(cfg, walk_in())
    seq = [e for e in types_of(events, person_id=1) if e != "PERSON_ZONE_CHANGED"]
    assert seq == [
        "PERSON_DETECTED",
        "PERSON_APPROACHING",
        "PERSON_WALKING_AWAY",
        "PERSON_LEAVING",
        "PERSON_LOST",
    ]


def test_walk_in_reaches_interaction_zone_and_goes_back_out(cfg):
    _, events = run_scenario(cfg, walk_in())
    zones = [e.data["zone"] for e in events if e.type is EventType.PERSON_ZONE_CHANGED]
    assert "INTERACTION" in zones
    assert zones.index("INTERACTION") < zones.index("FAR")
    # Close up the camera cannot see the whole person; the events must say so.
    close = [e for e in events if e.type is EventType.PERSON_ZONE_CHANGED and e.data["zone"] == "INTERACTION"]
    assert close[0].data["distance_reliable"] is False


def test_detector_dropouts_do_not_create_people_or_departures(cfg):
    _, events = run_scenario(cfg, flicker())
    assert types_of(events).count("PERSON_DETECTED") == 1
    assert "PERSON_LOST" not in types_of(events)
    assert "PERSON_RETURNED" not in types_of(events)


def test_someone_who_comes_back_is_returned_not_new(cfg):
    world, events = run_scenario(cfg, returning())
    kinds = types_of(events)
    assert kinds.count("PERSON_DETECTED") == 1
    returned = [e for e in events if e.type is EventType.PERSON_RETURNED]
    assert len(returned) == 1 and returned[0].person_id == 1
    assert world.person(1).returns == 1


def test_appearance_keeps_identities_when_people_swap_sides(cfg):
    _, events = run_scenario(cfg, two_people_swap())
    detected = {e.person_id: e.data["direction"] for e in events if e.type is EventType.PERSON_DETECTED}
    returned = {e.person_id: e.data["direction"] for e in events if e.type is EventType.PERSON_RETURNED}
    assert detected == {1: "left", 2: "right"}
    assert returned == {1: "right", 2: "left"}     # same people, other sides


def test_without_appearance_strangers_are_not_merged(cfg):
    # Same scenario, signatures stripped: nothing can prove they are the same
    # people after an 8-second absence, so they must be new.
    from binbrain.vision.tracker import Tracker

    tracker, world, events = Tracker(cfg), WorldModel(cfg), []
    for frame in two_people_swap().frames(cfg):
        dets = [d.__class__(d.label, d.score, d.box, None) for d in frame.detections]
        events += world.update(tracker.update(dets, frame.t), frame.t)
    assert types_of(events).count("PERSON_DETECTED") == 4
    assert "PERSON_RETURNED" not in types_of(events)


def test_robot_motion_is_not_mistaken_for_an_approaching_person(cfg):
    world, events = run_scenario(cfg, robot_drives_to_statue())
    assert "PERSON_APPROACHING" not in types_of(events)
    assert world.person(1).motion is Motion.STATIONARY


def test_the_same_robot_motion_without_ego_compensation_would_be_wrong(cfg):
    from binbrain.vision.tracker import Tracker

    tracker, world, events = Tracker(cfg), WorldModel(cfg), []
    for frame in robot_drives_to_statue().frames(cfg):
        events += world.update(tracker.update(frame.detections, frame.t), frame.t, ego_forward_mps=0.0)
    assert "PERSON_APPROACHING" in types_of(events)   # proves the test above tests something


def test_objects_are_news_once(cfg):
    world, events = run_scenario(cfg, person_with_cup())
    assert types_of(events).count("OBJECT_DETECTED") == 1
    assert world.visible_objects == ["cup"]


def test_zone_hysteresis_prevents_twitching(cfg):
    z = cfg.world.zones
    zone = Zone.UNKNOWN
    changes = 0
    for i in range(200):
        d = z.interact_max_m + (0.04 if i % 2 else -0.04)   # standing right on the boundary
        new = classify_zone(d, zone, z)
        changes += new is not zone
        zone = new
    assert changes == 1          # the initial classification, then nothing


def test_zone_bands_match_the_brief(cfg):
    z = cfg.world.zones
    expect = [(0.5, Zone.TOO_CLOSE), (1.2, Zone.INTERACTION), (1.8, Zone.APPROACH),
              (2.5, Zone.NOTICE), (4.0, Zone.FAR)]
    for d, zone in expect:
        assert classify_zone(d, Zone.UNKNOWN, z) is zone


def test_camera_silence_is_offline_not_empty(cfg):
    from binbrain.vision.tracker import Tracker

    tracker, world = Tracker(cfg), WorldModel(cfg)
    frames = list(walk_in().frames(cfg))[:20]
    for f in frames:
        world.update(tracker.update(f.detections, f.t), f.t)
    last = frames[-1].t
    assert world.summary(last)["people_visible"] == 1

    events = world.tick(last + cfg.camera.stale_after_s + 0.1)
    assert [e.type for e in events] == [EventType.VISION_OFFLINE]
    s = world.summary(last + 3.0)
    assert s["vision"] == "offline" and s["people"] is None      # unknown, never "nobody"
    assert world.tick(last + 10.0) == []                          # announced once
    # And no one was declared lost just because the camera went dark.
    assert all(not p.lost_announced for p in world.people)


def test_summary_is_compact_and_honest(cfg):
    world, _ = run_scenario(cfg, person_with_cup())
    s = world.summary(12.0)
    assert s["vision"] == "online"
    assert s["objects"] == ["cup"]
    (p,) = s["people"]
    assert set(p) == {"id", "distance_m", "distance_reliable", "direction", "zone",
                      "motion", "returning_visitor", "seen_for_s"}
    assert p["distance_m"] == pytest.approx(2.8, abs=0.15)


def test_forgotten_after_return_window():
    c = load_config(overrides={"world": {"return_window_s": 5.0}})
    world, events = run_scenario(c, returning())
    # Gone 12 s with a 5 s window: forgotten, so the return is a new person.
    assert types_of(events).count("PERSON_DETECTED") == 2
    assert "PERSON_RETURNED" not in types_of(events)
