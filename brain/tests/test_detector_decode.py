import numpy as np
import pytest

from binbrain.vision.detector import COCO_LABELS, decode_yolo, letterbox_params, nms

NC = len(COCO_LABELS)


def _v8_output(rows):
    """Build a YOLOv8-layout tensor [1, 4+nc, N] from (cx, cy, w, h, class_id, score)."""
    out = np.zeros((len(rows), 4 + NC), dtype=np.float32)
    for i, (cx, cy, w, h, c, s) in enumerate(rows):
        out[i, :4] = (cx, cy, w, h)
        out[i, 4 + c] = s
    return out.T[None]


def test_letterbox_params_for_4_3_camera():
    lb = letterbox_params(640, 480, 320)
    assert lb.scale == pytest.approx(0.5)
    assert (lb.pad_x, lb.pad_y) == (0.0, 40.0)


def test_decode_undoes_letterbox_into_normalised_coordinates():
    lb = letterbox_params(640, 480, 320)
    # A person occupying source pixels x 160..320, y 120..360 -> model pixels:
    #   x 80..160, y 60+40..180+40 = 100..220  ->  centre (120, 160), size 80x120
    out = _v8_output([(120.0, 160.0, 80.0, 120.0, 0, 0.9)])
    dets = decode_yolo(out, lb, COCO_LABELS, 0.4, 0.45)
    assert len(dets) == 1
    d = dets[0]
    assert d.label == "person" and d.score == pytest.approx(0.9)
    assert (d.box.x1, d.box.y1, d.box.x2, d.box.y2) == pytest.approx((0.25, 0.25, 0.5, 0.75), abs=1e-4)


def test_decode_suppresses_duplicates_but_not_other_classes():
    lb = letterbox_params(320, 320, 320)
    out = _v8_output([
        (100, 100, 60, 120, 0, 0.90),     # person
        (102, 101, 60, 118, 0, 0.70),     # same person again -> suppressed
        (101, 100, 58, 119, 41, 0.60),    # a cup in the same place -> kept (other class)
        (250, 250, 40, 40, 0, 0.20),      # below threshold
    ])
    dets = decode_yolo(out, lb, COCO_LABELS, 0.4, 0.45)
    assert sorted(d.label for d in dets) == ["cup", "person"]


def test_keep_labels_filters_before_nms():
    lb = letterbox_params(320, 320, 320)
    out = _v8_output([(100, 100, 60, 120, 0, 0.9), (200, 200, 30, 30, 41, 0.8)])
    dets = decode_yolo(out, lb, COCO_LABELS, 0.4, 0.45, keep_labels=("person",))
    assert [d.label for d in dets] == ["person"]


def test_yolov5_layout_uses_objectness():
    lb = letterbox_params(320, 320, 320)
    row = np.zeros((1, 5 + NC), dtype=np.float32)
    row[0, :5] = (160, 160, 50, 100, 0.5)     # objectness 0.5
    row[0, 5 + 0] = 0.9                         # class score 0.9 -> 0.45 combined
    dets = decode_yolo(row[None], lb, COCO_LABELS, 0.4, 0.45)
    assert len(dets) == 1 and dets[0].score == pytest.approx(0.45)


def test_wrong_label_count_is_a_clear_error():
    lb = letterbox_params(320, 320, 320)
    with pytest.raises(ValueError, match="detector.labels"):
        decode_yolo(np.zeros((1, 10, 100), dtype=np.float32), lb, COCO_LABELS, 0.4, 0.45)


def test_nms_basic():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
    assert nms(boxes, scores, 0.5) == [0, 2]
    assert nms(np.zeros((0, 4)), np.zeros(0), 0.5) == []
