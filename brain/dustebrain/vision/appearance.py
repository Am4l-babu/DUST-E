"""
appearance.py - "you again?" without face recognition.

A colour histogram of the torso is enough to tell the person in the red jumper
from the person in the blue one for a few minutes, which is all the robot needs
to avoid greeting the same human twice. It is not identity and is never stored:
it lives in RAM with the world model's short memory.

Pure numpy - no OpenCV - so it is testable anywhere and cheap on the A53.
"""

from __future__ import annotations

import numpy as np

from .types import BBox

HUE_BINS = 12
SAT_BINS = 4
GREY_BINS = 4
SAT_MIN = 0.20      # below this, hue is noise: the pixel goes in a brightness bin
VAL_MIN = 0.15      # too dark to have a colour at all
MAX_SAMPLES = 40    # the crop is subsampled to at most this many pixels per side


def signature_from_pixels(bgr: np.ndarray) -> np.ndarray | None:
    """L1-normalised hue/saturation histogram plus a brightness histogram for greys."""
    if bgr.ndim != 3 or bgr.shape[2] != 3 or bgr.shape[0] < 2 or bgr.shape[1] < 2:
        return None
    p = bgr.reshape(-1, 3).astype(np.float32) / 255.0
    b, g, r = p[:, 0], p[:, 1], p[:, 2]
    v = np.max(p, axis=1)
    mn = np.min(p, axis=1)
    c = v - mn
    s = np.divide(c, v, out=np.zeros_like(v), where=v > 0)

    h = np.zeros_like(v)
    nz = c > 1e-6
    is_r = nz & (v == r)
    is_g = nz & (v == g) & ~is_r
    is_b = nz & ~is_r & ~is_g
    safe_c = np.where(nz, c, 1.0)
    h[is_r] = ((g - b)[is_r] / safe_c[is_r]) % 6.0
    h[is_g] = (b - r)[is_g] / safe_c[is_g] + 2.0
    h[is_b] = (r - g)[is_b] / safe_c[is_b] + 4.0
    h = h / 6.0
    # Centre hue bin 0 on pure red, so red does not straddle the wraparound
    # and split between the first and the last bin.
    h = (h + 0.5 / HUE_BINS) % 1.0

    colour = (s >= SAT_MIN) & (v >= VAL_MIN)
    hs, _, _ = np.histogram2d(h[colour], s[colour], bins=(HUE_BINS, SAT_BINS),
                              range=((0.0, 1.0), (SAT_MIN, 1.0)))
    grey, _ = np.histogram(v[~colour], bins=GREY_BINS, range=(0.0, 1.0))
    sig = np.concatenate([hs.ravel(), grey.astype(np.float64)])
    total = sig.sum()
    if total <= 0:
        return None
    return (sig / total).astype(np.float32)


def torso_signature(image_bgr: np.ndarray, box: BBox) -> np.ndarray | None:
    """Signature of the torso region of a person box in a full frame.

    Upper-middle of the box, central 60 % of the width: mostly shirt, least
    background, no face (and nothing identifying is kept anyway).
    """
    ih, iw = image_bgr.shape[:2]
    x1 = int((box.cx - 0.3 * box.w) * iw)
    x2 = int((box.cx + 0.3 * box.w) * iw)
    y1 = int((box.y1 + 0.20 * box.h) * ih)
    y2 = int((box.y1 + 0.60 * box.h) * ih)
    x1, x2 = max(0, x1), min(iw, x2)
    y1, y2 = max(0, y1), min(ih, y2)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    step = max(1, max(x2 - x1, y2 - y1) // MAX_SAMPLES)
    return signature_from_pixels(image_bgr[y1:y2:step, x1:x2:step])


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Histogram intersection: 1.0 identical, 0.0 nothing in common."""
    return float(np.minimum(a, b).sum())


def blend(old: np.ndarray, new: np.ndarray, weight_new: float = 0.2) -> np.ndarray:
    mixed = (1.0 - weight_new) * old + weight_new * new
    total = mixed.sum()
    return (mixed / total).astype(np.float32) if total > 0 else old
