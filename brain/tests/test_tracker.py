import numpy as np
import pytest

from binbrain.vision import appearance
from binbrain.vision.tracker import Tracker, TrackStatus
from binbrain.vision.types import BBox, Detection

PERSON = BBox(0.40, 0.20, 0.55, 0.90)


def _det(box=PERSON, label="person"):
    return Detection(label, 0.8, box)


def test_single_false_positive_is_never_confirmed(cfg):
    tr = Tracker(cfg)
    tr.update([_det()], 0.0)
    for i in range(1, 10):
        tracks = tr.update([], i * 0.2)
    assert not any(t.visible for t in tracks)
    assert tr.tracks == []


def test_confirmed_after_confirm_hits(cfg):
    tr = Tracker(cfg)
    for i in range(cfg.tracker.confirm_hits):
        tracks = tr.update([_det()], i * 0.2)
    assert len(tracks) == 1 and tracks[0].status is TrackStatus.CONFIRMED


def test_same_track_follows_a_moving_box(cfg):
    tr = Tracker(cfg)
    ids = set()
    for i in range(15):
        dx = 0.01 * i
        box = BBox(PERSON.x1 + dx, PERSON.y1, PERSON.x2 + dx, PERSON.y2)
        ids |= {t.track_id for t in tr.update([_det(box)], i * 0.2)}
    assert ids == {1}


def test_labels_never_cross_associate(cfg):
    tr = Tracker(cfg)
    tr.update([_det(label="person")], 0.0)
    tracks = tr.update([_det(label="chair")], 0.2)
    assert {t.label for t in tracks} == {"person", "chair"}


def test_lost_then_forgotten(cfg):
    tr = Tracker(cfg)
    for i in range(3):
        tr.update([_det()], i * 0.2)
    t = 0.4 + cfg.tracker.lost_after_s + 0.1
    assert tr.update([], t)[0].status is TrackStatus.LOST
    assert tr.update([], 0.4 + cfg.tracker.forget_after_s + 0.1) == []


def test_revived_track_keeps_its_id(cfg):
    tr = Tracker(cfg)
    for i in range(3):
        tr.update([_det()], i * 0.2)
    tr.update([], 0.4 + cfg.tracker.lost_after_s + 0.1)
    tracks = tr.update([_det()], 0.4 + cfg.tracker.lost_after_s + 0.3)
    assert [(t.track_id, t.status) for t in tracks] == [(1, TrackStatus.CONFIRMED)]


def test_radial_velocity_sign(cfg):
    from binbrain.vision.geometry import box_for_standing_object

    tr = Tracker(cfg)
    for i in range(12):
        d = 6.0 - 0.5 * (i * 0.2)             # walking toward the camera at 0.5 m/s
        box = box_for_standing_object(d, 0.0, 1.7, 0.45, cfg.camera, cfg.geometry)
        tracks = tr.update([_det(box)], i * 0.2)
    assert tracks[0].radial_velocity_mps == pytest.approx(-0.5, abs=0.05)


def test_appearance_distinguishes_colours_and_tolerates_noise():
    rng = np.random.default_rng(3)

    def patch(bgr):
        base = np.array(bgr, dtype=np.int16)
        noisy = base + rng.integers(-20, 20, (16, 16, 3))
        return np.clip(noisy, 0, 255).astype(np.uint8)

    red1, red2 = appearance.signature_from_pixels(patch((40, 40, 200))), appearance.signature_from_pixels(patch((35, 45, 210)))
    blue = appearance.signature_from_pixels(patch((200, 60, 30)))
    grey = appearance.signature_from_pixels(patch((128, 128, 128)))
    assert appearance.similarity(red1, red2) > 0.8
    assert appearance.similarity(red1, blue) < 0.2
    assert appearance.similarity(red1, grey) < 0.2
    assert appearance.similarity(red1, red1) == pytest.approx(1.0)


def test_torso_signature_handles_tiny_boxes():
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    assert appearance.torso_signature(img, BBox(0.5, 0.5, 0.501, 0.501)) is None
