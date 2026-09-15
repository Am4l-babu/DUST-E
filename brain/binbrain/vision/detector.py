"""
detector.py - person and object detection on the UNO Q's CPU.

Default: a nano YOLO exported to ONNX at 320x320, run through OpenCV's DNN
module (no extra dependency) or onnxruntime (usually faster on ARM, if
installed). Chosen for what the board can sustain, not for benchmark rank:
the robot moves at walking pace, and a tracker fed at 4-5 Hz beats a bigger
model at under 1 Hz.

Supported output layouts, detected from the tensor shape:
    YOLOv8 / YOLO11   [1, 4 + classes, N]   xywh + class scores
    YOLOv5            [1, N, 5 + classes]   xywh + objectness + class scores

Decoding and NMS are pure numpy so they are unit-tested without a model file.
Export instructions and the licensing note are in brain/README.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from ..config import BrainConfig, DetectorConfig
from .types import BBox, Detection

log = logging.getLogger(__name__)

COCO_LABELS: tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush",
)


class Detector(Protocol):
    name: str

    def detect(self, image_bgr: np.ndarray) -> list[Detection]: ...


class NullDetector:
    """Configured off. Reports nothing - and the vision node reports that honestly."""

    name = "none"

    def detect(self, image_bgr: np.ndarray) -> list[Detection]:
        return []


# ---------------------------------------------------------------------------
# Letterboxing: resize keeping aspect ratio, pad to a square.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Letterbox:
    src_w: int
    src_h: int
    size: int
    scale: float
    pad_x: float
    pad_y: float


def letterbox_params(src_w: int, src_h: int, size: int) -> Letterbox:
    scale = min(size / src_w, size / src_h)
    new_w, new_h = round(src_w * scale), round(src_h * scale)
    # Whole-pixel padding, so the image placement and the decode agree exactly.
    return Letterbox(src_w, src_h, size, scale, float((size - new_w) // 2), float((size - new_h) // 2))


def letterbox_image(image_bgr: np.ndarray, lb: Letterbox) -> np.ndarray:
    import cv2  # lazy: see package docstring

    new_w, new_h = round(lb.src_w * lb.scale), round(lb.src_h * lb.scale)
    resized = cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((lb.size, lb.size, 3), 114, dtype=np.uint8)
    top, left = int(lb.pad_y), int(lb.pad_x)
    canvas[top:top + new_h, left:left + new_w] = resized
    return canvas


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------
def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Indices kept by greedy non-maximum suppression. boxes: (N, 4) xyxy."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        rest = order[1:]
        if rest.size == 0:
            break
        iw = np.clip(np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]), 0, None)
        ih = np.clip(np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]), 0, None)
        inter = iw * ih
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_threshold]
    return keep


def decode_yolo(
    output: np.ndarray,
    lb: Letterbox,
    labels: Sequence[str],
    score_threshold: float,
    nms_iou: float,
    keep_labels: Sequence[str] = (),
) -> list[Detection]:
    out = np.asarray(output, dtype=np.float32)
    if out.ndim == 3:
        out = out[0]
    if out.ndim != 2:
        raise ValueError(f"unexpected detector output shape {np.shape(output)}")

    nc = len(labels)
    widths = (4 + nc, 5 + nc)
    if out.shape[0] in widths and out.shape[1] not in widths:
        out = out.T                                  # YOLOv8 layout: [4+nc, N] -> [N, 4+nc]
    if out.shape[1] == 4 + nc:
        cls_scores = out[:, 4:]
    elif out.shape[1] == 5 + nc:
        cls_scores = out[:, 5:] * out[:, 4:5]
    else:
        raise ValueError(
            f"detector output has {out.shape[1]} columns; expected {4 + nc} (YOLOv8) or "
            f"{5 + nc} (YOLOv5) for {nc} labels - is detector.labels right for this model?")

    class_ids = cls_scores.argmax(axis=1)
    scores = cls_scores[np.arange(len(out)), class_ids]
    mask = scores >= score_threshold
    if keep_labels:
        wanted = np.array([labels[c] in keep_labels for c in range(nc)])
        mask &= wanted[class_ids]
    if not mask.any():
        return []

    xywh, scores, class_ids = out[mask, :4], scores[mask], class_ids[mask]
    xyxy = np.empty_like(xywh)
    xyxy[:, 0] = xywh[:, 0] - xywh[:, 2] / 2.0
    xyxy[:, 1] = xywh[:, 1] - xywh[:, 3] / 2.0
    xyxy[:, 2] = xywh[:, 0] + xywh[:, 2] / 2.0
    xyxy[:, 3] = xywh[:, 1] + xywh[:, 3] / 2.0
    # Model-input pixels -> source pixels -> normalised 0..1
    xyxy[:, [0, 2]] = (xyxy[:, [0, 2]] - lb.pad_x) / lb.scale / lb.src_w
    xyxy[:, [1, 3]] = (xyxy[:, [1, 3]] - lb.pad_y) / lb.scale / lb.src_h
    np.clip(xyxy, 0.0, 1.0, out=xyxy)

    detections: list[Detection] = []
    for c in np.unique(class_ids):
        idx = np.nonzero(class_ids == c)[0]
        for k in nms(xyxy[idx], scores[idx], nms_iou):
            j = idx[k]
            box = BBox(*(float(v) for v in xyxy[j]))
            if box.w > 0.0 and box.h > 0.0:
                detections.append(Detection(labels[int(c)], float(scores[j]), box))
    detections.sort(key=lambda d: d.score, reverse=True)
    return detections


# ---------------------------------------------------------------------------
# The real detector
# ---------------------------------------------------------------------------
class OnnxYoloDetector:
    def __init__(self, cfg: DetectorConfig, model_path: Path) -> None:
        self._cfg = cfg
        self._labels = cfg.labels or COCO_LABELS
        self.name = f"{model_path.name}@{cfg.backend}"

        if cfg.backend == "opencv":
            import cv2

            cv2.setNumThreads(cfg.threads)
            self._net = cv2.dnn.readNetFromONNX(str(model_path))
            self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            self._run = self._run_opencv
        elif cfg.backend == "onnxruntime":
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = cfg.threads
            self._session = ort.InferenceSession(
                str(model_path), sess_options=opts, providers=["CPUExecutionProvider"])
            self._input_name = self._session.get_inputs()[0].name
            self._run = self._run_ort
        else:
            raise ValueError(f"OnnxYoloDetector cannot use backend {cfg.backend!r}")
        log.info("detector %s ready (%d labels)", self.name, len(self._labels))

    def detect(self, image_bgr: np.ndarray) -> list[Detection]:
        h, w = image_bgr.shape[:2]
        lb = letterbox_params(w, h, self._cfg.input_size)
        canvas = letterbox_image(image_bgr, lb)
        blob = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
        return decode_yolo(self._run(blob), lb, self._labels, self._cfg.score_threshold,
                           self._cfg.nms_iou, self._cfg.keep_labels)

    def _run_opencv(self, blob: np.ndarray) -> np.ndarray:
        self._net.setInput(blob)
        return self._net.forward()

    def _run_ort(self, blob: np.ndarray) -> np.ndarray:
        return self._session.run(None, {self._input_name: blob})[0]


def create_detector(cfg: BrainConfig) -> Detector:
    d = cfg.detector
    if d.backend == "none":
        return NullDetector()
    path = cfg.resolve_path(d.model)
    if not path.is_file():
        raise FileNotFoundError(
            f"detector model not found: {path}\n"
            f"  Export one on a PC (see brain/README.md, 'Detector model'), copy it there,\n"
            f"  or set detector.backend: none to run without detection.")
    return OnnxYoloDetector(d, path)
