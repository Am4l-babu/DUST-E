"""
validator.py - what the brain is allowed to ask the body for.

This is the "COMMAND VALIDATOR" box in the architecture diagram, and it sits
between everything clever and everything physical. Three jobs:

  1. **Source policy.** Every command carries where it came from. The LLM may
     ask to look at someone; it may not ask for a wheel speed. That is not a
     prompt instruction the model could talk its way past - `vel` from
     `src: "llm"` is refused here, in code, before a byte reaches the body.
  2. **Range and enum checks.** Percentages, TTLs, durations and gesture names
     are clamped or refused. The body clamps again; this layer exists so the
     brain's own bugs are caught with a reason attached.
  3. **Rate limiting.** A loop gone wrong must not become a command storm.

`limits` deserves its own note: it may only ever *lower* a ceiling. There is
no message in this protocol that raises one. The ceilings in the firmware are
the real limit; this is the brain agreeing not to ask for more.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import BodyConfig
from . import protocol as P

# Command sources.
NAV = "nav"
SOCIAL = "social"
LLM = "llm"
DEBUG = "debug"
MANUAL = "manual"
SAFETY = "safety"
ALL_SOURCES = (NAV, SOCIAL, LLM, DEBUG, MANUAL, SAFETY)

# Who may send what. Anything absent from this table is refused outright.
POLICY: dict[str, tuple[str, ...]] = {
    P.HELLO: (MANUAL, DEBUG, NAV),
    P.HB: (NAV, MANUAL, DEBUG, SAFETY),
    P.VEL: (NAV, MANUAL, DEBUG),
    P.MOTION: (NAV, MANUAL, DEBUG),
    P.STOP: ALL_SOURCES,
    P.ESTOP: ALL_SOURCES,            # anyone may stop the robot
    P.RESET_ESTOP: (MANUAL,),        # only a human at the dashboard may clear it
    P.LIMITS: (MANUAL, DEBUG, SAFETY),
    P.LOOK: (NAV, SOCIAL, LLM, MANUAL, DEBUG),
    P.GESTURE: (SOCIAL, LLM, MANUAL, DEBUG),
    P.LID: (SOCIAL, LLM, MANUAL, DEBUG),
    P.FACE: (SOCIAL, LLM, MANUAL, DEBUG),
    P.LEDS: (SOCIAL, LLM, MANUAL, DEBUG),
    P.CLIP: (SOCIAL, LLM, MANUAL, DEBUG),
    P.PCM: (SOCIAL, LLM, MANUAL, DEBUG),
    P.PCM_STOP: ALL_SOURCES,
}

GESTURES = ("NOD", "SHAKE", "EYE_WAVE", "SQUINT", "TILT", "JITTER", "SLEEP", "WAKE", "CENTER")
MOTIONS = ("STOP", "MOVE_FORWARD", "MOVE_BACKWARD", "TURN_LEFT", "TURN_RIGHT", "ROTATE")
LID_ACTIONS = ("OPEN", "CLOSE", "PEEK")
SPEEDS = ("SLOW", "NORMAL")


class CommandRejected(Exception):
    def __init__(self, code: str, reason: str) -> None:
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


@dataclass
class Ceilings:
    auto_max_pct: int
    manual_max_pct: int


@dataclass
class _Bucket:
    tokens: float
    last_ms: int = 0


class Validator:
    def __init__(self, cfg: BodyConfig) -> None:
        self._cfg = cfg
        self.ceilings = Ceilings(cfg.auto_max_pct, cfg.manual_max_pct)
        self._buckets: dict[str, _Bucket] = {}
        self.rejected = 0

    # ------------------------------------------------------------------
    def validate(self, msg: dict[str, Any], now_ms: int) -> dict[str, Any]:
        """Returns the message, clamped where clamping is safe. Raises otherwise."""
        try:
            return self._validate(msg, now_ms)
        except CommandRejected:
            self.rejected += 1
            raise

    def ceiling_for(self, src: str) -> int:
        return self.ceilings.manual_max_pct if src in (MANUAL, DEBUG) else self.ceilings.auto_max_pct

    # ------------------------------------------------------------------
    def _validate(self, msg: dict[str, Any], now_ms: int) -> dict[str, Any]:
        out = dict(msg)
        type_ = out.get("type")
        src = out.get("src", NAV)
        if not isinstance(type_, str) or type_ not in POLICY:
            raise CommandRejected(P.E_SCHEMA, f"unknown command type {type_!r}")
        if src not in ALL_SOURCES:
            raise CommandRejected(P.E_SCHEMA, f"unknown source {src!r}")
        if src not in POLICY[type_]:
            raise CommandRejected(P.E_SRC_FORBIDDEN, f"{src} may not send {type_}")
        out["src"] = src

        # An emergency stop is never rate limited, and never waits for a token.
        if type_ not in (P.ESTOP, P.STOP) and not self._take_token(type_, now_ms):
            raise CommandRejected(P.E_RATE, f"{type_} exceeded {self._cfg.rate_limit_hz} Hz")

        if type_ == P.VEL:
            self._clamp_vel(out, src)
        elif type_ == P.MOTION:
            self._clamp_motion(out, src)
        elif type_ == P.LIMITS:
            self._apply_limits(out)
        elif type_ == P.LOOK:
            out["x"] = _clamp_float(out.get("x", 0.0), -1.0, 1.0, "look.x")
            out["y"] = _clamp_float(out.get("y", 0.0), -1.0, 1.0, "look.y")
            out["ms"] = _clamp_int(out.get("ms", 300), 20, self._cfg.max_gesture_ms, "look.ms")
        elif type_ == P.GESTURE:
            _require_enum(out.get("name"), GESTURES, "gesture.name")
        elif type_ == P.LID:
            _require_enum(out.get("action"), LID_ACTIONS, "lid.action")
            if "speed" in out:
                _require_enum(out["speed"], SPEEDS, "lid.speed")
        return out

    # ------------------------------------------------------------------
    def _clamp_vel(self, out: dict[str, Any], src: str) -> None:
        ceiling = self.ceiling_for(src)
        out["l"] = _clamp_int(out.get("l", 0), -ceiling, ceiling, "vel.l")
        out["r"] = _clamp_int(out.get("r", 0), -ceiling, ceiling, "vel.r")
        out["ttl"] = _clamp_int(out.get("ttl", self._cfg.cmd_ttl_default_ms),
                                1, self._cfg.cmd_ttl_max_ms, "vel.ttl")

    def _clamp_motion(self, out: dict[str, Any], src: str) -> None:
        _require_enum(out.get("cmd"), MOTIONS, "motion.cmd")
        ceiling = self.ceiling_for(src)
        out["speed"] = _clamp_int(out.get("speed", ceiling), 0, ceiling, "motion.speed")
        out["ms"] = _clamp_int(out.get("ms", 500), 1, self._cfg.max_motion_ms, "motion.ms")

    def _apply_limits(self, out: dict[str, Any]) -> None:
        """Lower only. Nothing in this protocol can raise a ceiling."""
        auto = out.get("auto_max", self.ceilings.auto_max_pct)
        manual = out.get("manual_max", self.ceilings.manual_max_pct)
        auto = _clamp_int(auto, 1, 100, "limits.auto_max")
        manual = _clamp_int(manual, 1, 100, "limits.manual_max")
        self.ceilings.auto_max_pct = min(self.ceilings.auto_max_pct, auto)
        self.ceilings.manual_max_pct = min(self.ceilings.manual_max_pct, manual)
        out["auto_max"] = self.ceilings.auto_max_pct
        out["manual_max"] = self.ceilings.manual_max_pct

    def _take_token(self, type_: str, now_ms: int) -> bool:
        rate = float(self._cfg.rate_limit_hz)
        bucket = self._buckets.get(type_)
        if bucket is None:
            self._buckets[type_] = _Bucket(tokens=rate - 1.0, last_ms=now_ms)
            return True
        elapsed = max(0, now_ms - bucket.last_ms)
        bucket.tokens = min(rate, bucket.tokens + rate * elapsed / 1000.0)
        bucket.last_ms = now_ms
        if bucket.tokens < 1.0:
            return False
        bucket.tokens -= 1.0
        return True


# ---------------------------------------------------------------------------
def _clamp_int(value: Any, lo: int, hi: int, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CommandRejected(P.E_SCHEMA, f"{where} must be a number, got {value!r}")
    return int(max(lo, min(hi, round(value))))


def _clamp_float(value: Any, lo: float, hi: float, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CommandRejected(P.E_SCHEMA, f"{where} must be a number, got {value!r}")
    return float(max(lo, min(hi, value)))


def _require_enum(value: Any, allowed: tuple[str, ...], where: str) -> None:
    if value not in allowed:
        raise CommandRejected(P.E_RANGE, f"{where}={value!r} is not one of {allowed}")
