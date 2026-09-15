"""
geometry.py - where a person is, from one camera, stated honestly.

Bearing comes from the box's horizontal centre through a pinhole model.

Distance has three estimators, tried in order of trustworthiness:

  ground  The feet are in frame. With the camera height and pitch known, the
          angle down to the bottom edge of the box gives the range along the
          floor. Independent of how tall the person is, so it works for
          children and seated people. Reliable.
  height  Head and feet are both in frame. Angular height against an assumed
          person height. Independent of camera height. Reliable-ish.
  width   The box is cut off top and/or bottom - the normal case up close for
          a camera at bin height. Shoulder width against the box width.
          Arms and pose move it a lot. NOT reliable.

When the feet are cut off by the bottom of the frame, the person must be
closer than the distance at which the floor leaves the frame, so the estimate
is clamped to that bound. That bound is the one number up close that is
actually trustworthy, and it errs in the safe direction.

The camera is never the collision sensor. The body's range sensors are.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import CameraConfig, GeometryConfig
from .types import BBox


def _k(fov_deg: float) -> float:
    """Normalised image span per unit tan(angle)."""
    return 2.0 * math.tan(math.radians(fov_deg) / 2.0)


def bearing_deg(cx: float, hfov_deg: float) -> float:
    """Horizontal angle of a normalised x; positive is to the robot's right."""
    return math.degrees(math.atan((cx - 0.5) * _k(hfov_deg)))


def cx_for_bearing(bearing: float, hfov_deg: float) -> float:
    return 0.5 + math.tan(math.radians(bearing)) / _k(hfov_deg)


def angle_below_horizon_deg(y: float, vfov_deg: float, pitch_up_deg: float) -> float:
    """How far below the horizon the ray through normalised row y points."""
    below_axis = math.degrees(math.atan((y - 0.5) * _k(vfov_deg)))
    return below_axis - pitch_up_deg


def row_for_angle_below_horizon(angle_deg: float, vfov_deg: float, pitch_up_deg: float) -> float:
    return 0.5 + math.tan(math.radians(angle_deg + pitch_up_deg)) / _k(vfov_deg)


def feet_visible_beyond_m(cam: CameraConfig, geom: GeometryConfig) -> float | None:
    """Closer than this, a standing person's feet are below the frame.

    None if the camera is pitched so far up that the floor is never in view.
    """
    lowest = angle_below_horizon_deg(1.0, cam.vfov_deg, geom.camera_pitch_deg)
    if lowest <= 0.0:
        return None
    return geom.camera_height_m / math.tan(math.radians(lowest))


@dataclass(frozen=True)
class RangeEstimate:
    distance_m: float | None
    reliable: bool
    method: str                      # ground | height | width | bound | none
    upper_bound_m: float | None      # the person is certainly closer than this, if set


NO_RANGE = RangeEstimate(None, False, "none", None)


def estimate_range(box: BBox, cam: CameraConfig, geom: GeometryConfig) -> RangeEstimate:
    m = geom.edge_margin
    top_cut = box.y1 <= m
    bottom_cut = box.y2 >= 1.0 - m
    side_cut = box.x1 <= m or box.x2 >= 1.0 - m
    pitch = geom.camera_pitch_deg

    d: float | None = None
    method = "none"
    reliable = False

    if not bottom_cut:
        a = angle_below_horizon_deg(box.y2, cam.vfov_deg, pitch)
        if a >= geom.min_ground_angle_deg:
            d = geom.camera_height_m / math.tan(math.radians(a))
            method, reliable = "ground", True

    if d is None and not top_cut and not bottom_cut:
        up = -angle_below_horizon_deg(box.y1, cam.vfov_deg, pitch)
        down = angle_below_horizon_deg(box.y2, cam.vfov_deg, pitch)
        span = math.tan(math.radians(up)) + math.tan(math.radians(down))
        if span > 1e-6:
            d = geom.person_height_m / span
            method, reliable = "height", True

    if d is None and not side_cut and box.w > 1e-6:
        d = geom.person_width_m / (box.w * _k(cam.hfov_deg))
        method, reliable = "width", False

    upper: float | None = None
    if bottom_cut:
        upper = feet_visible_beyond_m(cam, geom)
        if upper is not None:
            if d is None:
                d, method = upper, "bound"
            elif d > upper:
                d = upper
            reliable = False

    if d is None:
        return NO_RANGE
    return RangeEstimate(min(d, geom.max_range_m), reliable, method, upper)


def box_for_standing_object(
    distance_m: float,
    bearing: float,
    height_m: float,
    width_m: float,
    cam: CameraConfig,
    geom: GeometryConfig,
) -> BBox | None:
    """The inverse of estimate_range: where an object on the floor appears.

    Used by the simulator and the tests. Returns None when it is entirely out
    of frame. The box is clipped to the frame, exactly as a detector's would be.
    """
    if distance_m <= 0.0:
        return None
    pitch = geom.camera_pitch_deg
    feet = math.degrees(math.atan(geom.camera_height_m / distance_m))
    head = -math.degrees(math.atan((height_m - geom.camera_height_m) / distance_m))
    y2 = row_for_angle_below_horizon(feet, cam.vfov_deg, pitch)
    y1 = row_for_angle_below_horizon(head, cam.vfov_deg, pitch)
    w = width_m / (distance_m * _k(cam.hfov_deg))
    cx = cx_for_bearing(bearing, cam.hfov_deg)
    raw = BBox(cx - w / 2.0, y1, cx + w / 2.0, y2)
    if raw.x2 <= 0.0 or raw.x1 >= 1.0 or raw.y2 <= 0.0 or raw.y1 >= 1.0:
        return None
    return raw.clipped()
