import pytest

from dustebrain.config import load_config
from dustebrain.vision.geometry import (
    bearing_deg,
    box_for_standing_object,
    cx_for_bearing,
    estimate_range,
    feet_visible_beyond_m,
)
from dustebrain.vision.types import BBox


@pytest.mark.parametrize("b", [-30.0, -5.0, 0.0, 12.0, 34.0])
def test_bearing_round_trip(cfg, b):
    assert bearing_deg(cx_for_bearing(b, cfg.camera.hfov_deg), cfg.camera.hfov_deg) == pytest.approx(b)


def test_bearing_sign_convention(cfg):
    assert bearing_deg(0.9, cfg.camera.hfov_deg) > 0      # right of centre is positive
    assert bearing_deg(0.5, cfg.camera.hfov_deg) == 0.0


@pytest.mark.parametrize("d", [3.0, 4.5, 7.0])
def test_ground_estimate_is_exact_when_feet_are_visible(cfg, d):
    box = box_for_standing_object(d, 0.0, 1.70, 0.45, cfg.camera, cfg.geometry)
    r = estimate_range(box, cfg.camera, cfg.geometry)
    assert r.method == "ground" and r.reliable
    assert r.distance_m == pytest.approx(d, rel=1e-3)


def test_ground_estimate_ignores_person_height(cfg):
    # A child: height assumptions would be 40 % off, the floor is not.
    box = box_for_standing_object(3.5, 0.0, 1.10, 0.30, cfg.camera, cfg.geometry)
    r = estimate_range(box, cfg.camera, cfg.geometry)
    assert r.method == "ground"
    assert r.distance_m == pytest.approx(3.5, rel=1e-3)


def test_height_estimate_when_floor_is_not_usable():
    # Pitched down hard: feet near the horizon row are unusable, head and feet in frame.
    c = load_config(overrides={"geometry": {"min_ground_angle_deg": 30.0}})
    box = box_for_standing_object(5.0, 0.0, 1.70, 0.45, c.camera, c.geometry)
    r = estimate_range(box, c.camera, c.geometry)
    assert r.method == "height"
    assert r.distance_m == pytest.approx(5.0, rel=1e-3)


def test_close_person_is_never_reported_farther_than_the_floor_allows(cfg):
    limit = feet_visible_beyond_m(cfg.camera, cfg.geometry)
    assert limit is not None and 1.0 < limit < 3.0
    for d in (0.7, 1.0, 1.4):
        box = box_for_standing_object(d, 0.0, 1.70, 0.45, cfg.camera, cfg.geometry)
        r = estimate_range(box, cfg.camera, cfg.geometry)
        assert not r.reliable                       # cut off: say so
        assert r.upper_bound_m == pytest.approx(limit)
        assert r.distance_m <= limit                # and err on the close side


def test_wide_box_without_width_clue_falls_back_to_the_bound(cfg):
    # Cut off on every side: no ground, no height, no width. Only the bound is left.
    r = estimate_range(BBox(0.0, 0.0, 1.0, 1.0), cfg.camera, cfg.geometry)
    assert r.method == "bound" and not r.reliable
    assert r.distance_m == pytest.approx(feet_visible_beyond_m(cfg.camera, cfg.geometry))


def test_out_of_frame_object_has_no_box(cfg):
    assert box_for_standing_object(2.0, 80.0, 1.7, 0.45, cfg.camera, cfg.geometry) is None
