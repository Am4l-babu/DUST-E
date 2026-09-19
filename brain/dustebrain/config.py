"""
config.py - load, merge and validate brain/config/default.yaml.

The dataclasses below deliberately have no defaults. default.yaml is the only
place a default lives, an override file only carries what it changes, and the
builder refuses unknown and missing keys - so a typo in a threshold is a loud
error at startup instead of a quietly ignored line at a demo.
"""

from __future__ import annotations

import copy
import types
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping, Union, get_args, get_origin, get_type_hints

import yaml

BRAIN_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = BRAIN_DIR / "config" / "default.yaml"


class ConfigError(ValueError):
    """The configuration is malformed or internally contradictory."""


@dataclass(frozen=True)
class CameraConfig:
    source: str
    width: int
    height: int
    fps: float
    hfov_deg: float
    vfov_deg: float
    flip_horizontal: bool
    stale_after_s: float
    reconnect_s: float


@dataclass(frozen=True)
class DetectorConfig:
    backend: str
    model: str
    input_size: int
    score_threshold: float
    nms_iou: float
    rate_hz: float
    threads: int
    labels: tuple[str, ...]
    keep_labels: tuple[str, ...]


@dataclass(frozen=True)
class GeometryConfig:
    camera_height_m: float
    camera_pitch_deg: float
    person_height_m: float
    person_width_m: float
    edge_margin: float
    min_ground_angle_deg: float
    max_range_m: float
    ranged_labels: tuple[str, ...]


@dataclass(frozen=True)
class TrackerConfig:
    iou_match: float
    max_center_jump: float
    confirm_hits: int
    lost_after_s: float
    forget_after_s: float
    box_smoothing: float
    distance_smoothing: float
    velocity_window_s: float
    min_velocity_samples: int


@dataclass(frozen=True)
class ZonesConfig:
    too_close_m: float
    interact_max_m: float
    approach_max_m: float
    notice_max_m: float
    hysteresis_m: float

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (self.too_close_m, self.interact_max_m, self.approach_max_m, self.notice_max_m)


@dataclass(frozen=True)
class WorldConfig:
    person_label: str
    person_lost_s: float
    return_window_s: float
    reassociate_s: float
    reassociate_center_dist: float
    reid_similarity: float
    approach_speed_mps: float
    leave_speed_mps: float
    stationary_speed_mps: float
    motion_confirm_s: float
    object_memory_s: float
    ahead_deg: float
    zones: ZonesConfig


@dataclass(frozen=True)
class BodyConfig:
    heartbeat_ms: int
    link_timeout_ms: int
    cmd_ttl_default_ms: int
    cmd_ttl_max_ms: int
    tick_ms: int
    accel_pct_per_tick: int
    decel_mult: int
    auto_max_pct: int
    manual_max_pct: int
    motion_ok_window_ms: int
    motion_ok_min_edges: int
    escape_duty_pct: int
    escape_ms: int
    escape_cooldown_ms: int
    battery_low_mv: int
    battery_critical_mv: int
    max_motion_ms: int
    max_gesture_ms: int
    rate_limit_hz: int


@dataclass(frozen=True)
class LoggingConfig:
    level: str
    events_jsonl: str


@dataclass(frozen=True)
class BrainConfig:
    camera: CameraConfig
    detector: DetectorConfig
    geometry: GeometryConfig
    tracker: TrackerConfig
    world: WorldConfig
    body: BodyConfig
    logging: LoggingConfig

    def resolve_path(self, p: str) -> Path:
        """Relative paths in the config are relative to brain/, not the CWD."""
        path = Path(p)
        return path if path.is_absolute() else BRAIN_DIR / path


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_config(
    path: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> BrainConfig:
    """default.yaml, then the optional override file, then in-code overrides."""
    data = _read_yaml(DEFAULT_CONFIG_PATH)
    if path is not None:
        data = deep_merge(data, _read_yaml(Path(path)))
    if overrides:
        data = deep_merge(data, overrides)
    cfg = _build(BrainConfig, data, "config")
    validate(cfg)
    return cfg


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise ConfigError(f"config file not found: {path}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    return data


def _build(cls: type, data: Mapping[str, Any], where: str) -> Any:
    if not isinstance(data, Mapping):
        raise ConfigError(f"{where}: expected a mapping, got {type(data).__name__}")
    hints = get_type_hints(cls)
    names = [f.name for f in fields(cls)]
    unknown = sorted(set(data) - set(names))
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {unknown} - typo? valid keys are {names}")
    missing = [n for n in names if n not in data]
    if missing:
        raise ConfigError(f"{where}: missing key(s) {missing}")
    return cls(**{n: _coerce(data[n], hints[n], f"{where}.{n}") for n in names})


def _coerce(value: Any, tp: Any, where: str) -> Any:
    if is_dataclass(tp):
        return _build(tp, value, where)

    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        for arg in get_args(tp):
            try:
                return _coerce(value, arg, where)
            except ConfigError:
                continue
        raise ConfigError(f"{where}: {value!r} is not {tp}")
    if origin is tuple:
        if not isinstance(value, (list, tuple)):
            raise ConfigError(f"{where}: expected a list, got {value!r}")
        (item_tp, _ellipsis) = get_args(tp)
        return tuple(_coerce(v, item_tp, f"{where}[{i}]") for i, v in enumerate(value))

    # bool is a subclass of int in Python; "enabled: 1" and "width: true" are
    # both mistakes worth catching.
    if tp is bool and isinstance(value, bool):
        return value
    if tp is int and isinstance(value, int) and not isinstance(value, bool):
        return value
    if tp is float and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if tp is str and isinstance(value, (str, int)) and not isinstance(value, bool):
        return str(value)   # camera.source: 0 and "0" mean the same device
    if tp in (bool, int, float, str):
        raise ConfigError(f"{where}: expected {tp.__name__}, got {value!r}")
    raise ConfigError(f"{where}: unsupported config type {tp!r}")


# ---------------------------------------------------------------------------
# Validation - contradictions a type check cannot see
# ---------------------------------------------------------------------------
def validate(cfg: BrainConfig) -> None:
    problems: list[str] = []

    def need(ok: bool, msg: str) -> None:
        if not ok:
            problems.append(msg)

    c, d, g, t, w = cfg.camera, cfg.detector, cfg.geometry, cfg.tracker, cfg.world
    z = w.zones

    need(c.width > 0 and c.height > 0, "camera width/height must be positive")
    need(c.fps > 0, "camera.fps must be positive")
    need(10.0 <= c.hfov_deg <= 170.0, "camera.hfov_deg must be within 10..170")
    need(10.0 <= c.vfov_deg <= 170.0, "camera.vfov_deg must be within 10..170")
    need(c.stale_after_s > 0, "camera.stale_after_s must be positive")

    need(d.backend in ("opencv", "onnxruntime", "none"), f"detector.backend {d.backend!r} unknown")
    need(d.input_size >= 64 and d.input_size % 32 == 0, "detector.input_size must be a multiple of 32, >= 64")
    need(0.0 < d.score_threshold < 1.0, "detector.score_threshold must be within (0, 1)")
    need(0.0 < d.nms_iou < 1.0, "detector.nms_iou must be within (0, 1)")
    need(d.rate_hz > 0, "detector.rate_hz must be positive")
    need(d.threads >= 1, "detector.threads must be >= 1")

    need(g.camera_height_m > 0, "geometry.camera_height_m must be positive")
    need(-45.0 <= g.camera_pitch_deg <= 45.0, "geometry.camera_pitch_deg must be within -45..45")
    need(g.person_height_m > g.camera_height_m,
         "geometry.person_height_m must exceed camera_height_m (the ground/height maths assume it)")
    need(g.person_width_m > 0, "geometry.person_width_m must be positive")
    need(0.0 <= g.edge_margin < 0.2, "geometry.edge_margin must be within 0..0.2")
    need(g.max_range_m > z.notice_max_m, "geometry.max_range_m must exceed world.zones.notice_max_m")

    need(0.0 < t.iou_match < 1.0, "tracker.iou_match must be within (0, 1)")
    need(t.confirm_hits >= 1, "tracker.confirm_hits must be >= 1")
    need(0.0 < t.lost_after_s < t.forget_after_s, "tracker: need 0 < lost_after_s < forget_after_s")
    need(0.0 < t.box_smoothing <= 1.0, "tracker.box_smoothing must be within (0, 1]")
    need(0.0 < t.distance_smoothing <= 1.0, "tracker.distance_smoothing must be within (0, 1]")
    need(t.velocity_window_s > 0, "tracker.velocity_window_s must be positive")
    need(t.min_velocity_samples >= 2, "tracker.min_velocity_samples must be >= 2")

    need(w.person_lost_s >= t.lost_after_s, "world.person_lost_s must be >= tracker.lost_after_s")
    need(w.return_window_s > w.person_lost_s, "world.return_window_s must exceed person_lost_s")
    need(0.0 < w.reid_similarity <= 1.0, "world.reid_similarity must be within (0, 1]")
    need(w.stationary_speed_mps < min(w.approach_speed_mps, w.leave_speed_mps),
         "world.stationary_speed_mps must be below approach/leave speeds (it is the deadband)")

    b = z.bounds
    need(all(0.0 < lo < hi for lo, hi in zip(b, b[1:])),
         "world.zones must increase strictly: too_close < interact_max < approach_max < notice_max")
    min_gap = min(hi - lo for lo, hi in zip(b, b[1:]))
    need(0.0 <= z.hysteresis_m < min_gap / 2,
         f"world.zones.hysteresis_m must be below half the narrowest zone ({min_gap / 2:.2f} m)")

    b = cfg.body
    need(b.heartbeat_ms > 0, "body.heartbeat_ms must be positive")
    need(b.link_timeout_ms >= 2 * b.heartbeat_ms,
         "body.link_timeout_ms must allow at least two missed heartbeats")
    need(0 < b.cmd_ttl_default_ms <= b.cmd_ttl_max_ms,
         "body: need 0 < cmd_ttl_default_ms <= cmd_ttl_max_ms")
    need(b.tick_ms > 0 and b.accel_pct_per_tick >= 1, "body: tick_ms and accel_pct_per_tick must be >= 1")
    need(b.decel_mult >= 1, "body.decel_mult must be >= 1 - stopping may never be slower than starting")
    need(0 < b.auto_max_pct <= b.manual_max_pct <= 100,
         "body: need 0 < auto_max_pct <= manual_max_pct <= 100")
    need(b.motion_ok_window_ms > 0 and b.motion_ok_min_edges >= 1,
         "body: motion_ok window and edge count must be positive")
    need(0 < b.escape_duty_pct <= b.auto_max_pct,
         "body.escape_duty_pct must be within the autonomous ceiling")
    need(b.escape_ms > 0 and b.escape_cooldown_ms >= b.escape_ms,
         "body: escape_cooldown_ms must be at least escape_ms")
    need(0 < b.battery_critical_mv < b.battery_low_mv,
         "body: need 0 < battery_critical_mv < battery_low_mv")
    need(b.max_motion_ms > 0 and b.max_gesture_ms > 0, "body: motion/gesture caps must be positive")
    need(b.rate_limit_hz >= 1, "body.rate_limit_hz must be >= 1")

    if problems:
        raise ConfigError("invalid configuration:\n  - " + "\n  - ".join(problems))
