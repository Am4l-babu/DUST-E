"""
types.py - boxes and detections, in normalised image coordinates.

Everything above the detector works in 0..1 coordinates (x right, y down) so
that nothing downstream depends on the camera resolution or the model's input
size. Pixels exist only inside the detector and the on-screen overlay.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class BBox:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def w(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def h(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0

    @property
    def area(self) -> float:
        return self.w * self.h

    def iou(self, other: BBox) -> float:
        ix = max(0.0, min(self.x2, other.x2) - max(self.x1, other.x1))
        iy = max(0.0, min(self.y2, other.y2) - max(self.y1, other.y1))
        inter = ix * iy
        union = self.area + other.area - inter
        return inter / union if union > 0.0 else 0.0

    def center_distance(self, other: BBox) -> float:
        return math.hypot(self.cx - other.cx, self.cy - other.cy)

    def blend(self, other: BBox, alpha: float) -> BBox:
        """Move alpha of the way toward other (alpha = weight of the new box)."""
        a = alpha
        return BBox(
            self.x1 + a * (other.x1 - self.x1),
            self.y1 + a * (other.y1 - self.y1),
            self.x2 + a * (other.x2 - self.x2),
            self.y2 + a * (other.y2 - self.y2),
        )

    def clipped(self) -> BBox:
        return BBox(
            min(1.0, max(0.0, self.x1)),
            min(1.0, max(0.0, self.y1)),
            min(1.0, max(0.0, self.x2)),
            min(1.0, max(0.0, self.y2)),
        )

    def to_list(self, ndigits: int = 4) -> list[float]:
        return [round(v, ndigits) for v in (self.x1, self.y1, self.x2, self.y2)]


@dataclass(frozen=True)
class Detection:
    label: str
    score: float
    box: BBox
    # Appearance histogram (appearance.py). Optional: a detector knows nothing
    # about it, and the world model works without it, just with shorter memory.
    signature: np.ndarray | None = field(default=None, compare=False, repr=False)
