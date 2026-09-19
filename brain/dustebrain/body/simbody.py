"""
simbody.py - the body's reflex safety, in Python, as the reference the
firmware must match.

The XIAO ESP32-S3 is the only thing that can energise a motor, so its rules
are the ones that matter. Writing them here first means they can be tested
against the failsafe matrix before a single wire is soldered, and it gives the
firmware an exact specification instead of a paragraph of prose.

The rules, in the order the body applies them:

  1. E-stop latched            -> hard stop. Cleared only by `reset_estop`
                                  from a human, and only once the hardware
                                  contact has been released.
  2. Battery critical          -> refuse to move.
  3. No heartbeat for          -> hard stop. Covers a crashed brain, a yanked
     link_timeout_ms              USB cable and a hung Linux side alike.
  4. Command TTL expired       -> ramp the target to zero. Not a fault: it is
                                  the normal end of a velocity command.
  5. MOTION_OK pulses absent   -> forward motion blocked. Reverse allowed at
                                  escape_duty_pct for escape_ms, then it must
                                  stop and wait out a cooldown - sensors all
                                  face forward, so reversing is the one safe
                                  escape and it must not become a habit.
  6. Ceiling + ramp            -> nothing above the current ceiling, and
                                  deceleration is always allowed to outrun
                                  acceleration.

Anything not on this list cannot move the robot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import BodyConfig
from . import protocol as P

# Inhibit reasons, in the order they are checked.
INHIBIT_NONE = ""
INHIBIT_ESTOP = "EMERGENCY STOP"
INHIBIT_BATTERY = "BATTERY CRITICAL"
INHIBIT_LINK = "LINK TIMEOUT"
INHIBIT_MOTION_OK = "SENSOR VETO"


@dataclass
class _Escape:
    started_ms: int | None = None
    last_end_ms: int | None = None


@dataclass
class SimBody:
    cfg: BodyConfig
    now_ms: int = 0

    # Live ceiling. Starts at the configured value and can only be lowered;
    # kept here rather than on cfg, which is frozen and shared.
    auto_max_pct: int = 0

    # link
    last_hb_ms: int | None = None
    handshaken: bool = False

    # motion intent
    target_l: int = 0
    target_r: int = 0
    cmd_expiry_ms: int = 0
    duty_l: int = 0
    duty_r: int = 0
    _last_tick_ms: int | None = None   # None = the first tick is due immediately

    # safety inputs
    estop: bool = False
    estop_reason: str = ""
    estop_contact_closed: bool = True      # the hardware mushroom is released
    battery_mv: int | None = None
    _motion_ok_edges: list[int] = field(default_factory=list)
    _escape: _Escape = field(default_factory=_Escape)

    # bookkeeping
    inhibit: str = INHIBIT_NONE
    crc_errors: int = 0
    rejected: int = 0
    received: int = 0   # messages successfully decoded and handled
    events: list[dict[str, Any]] = field(default_factory=list)
    _reader: P.LineReader = field(default_factory=P.LineReader)
    _framer: P.Framer = field(default_factory=P.Framer)

    def __post_init__(self) -> None:
        if not self.auto_max_pct:
            self.auto_max_pct = self.cfg.auto_max_pct

    # ------------------------------------------------------------------
    # Inputs from the outside world
    # ------------------------------------------------------------------
    def feed(self, data: bytes, now_ms: int) -> list[dict[str, Any]]:
        """Bytes from the brain. Returns the messages the body sends back."""
        self.now_ms = now_ms
        replies: list[dict[str, Any]] = []
        for item in self._reader.feed(data):
            if isinstance(item, P.ProtocolError):
                if item.code == P.E_CRC:
                    self.crc_errors += 1
                self.rejected += 1
                continue                      # a corrupt line is dropped, never guessed
            self.received += 1
            replies.extend(self.handle(item, now_ms))
        return replies

    def motion_ok_edge(self, now_ms: int) -> None:
        """One edge of the MOTION_OK pulse train from the UNO Q MCU."""
        self.now_ms = now_ms
        self._motion_ok_edges.append(now_ms)
        cutoff = now_ms - self.cfg.motion_ok_window_ms
        self._motion_ok_edges = [t for t in self._motion_ok_edges if t >= cutoff]

    def press_estop_button(self, now_ms: int) -> None:
        """The hardware mushroom. Cuts motor power; the body only observes it."""
        self.estop_contact_closed = False
        self._latch_estop("hardware button", now_ms)

    def release_estop_button(self) -> None:
        self.estop_contact_closed = True

    def motion_ok(self, now_ms: int) -> bool:
        cutoff = now_ms - self.cfg.motion_ok_window_ms
        return len([t for t in self._motion_ok_edges if t >= cutoff]) >= self.cfg.motion_ok_min_edges

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def handle(self, msg: dict[str, Any], now_ms: int) -> list[dict[str, Any]]:
        self.now_ms = now_ms
        type_ = msg.get("type")
        seq = msg.get("seq", 0)

        if type_ == P.HELLO:
            self.handshaken = True
            self.last_hb_ms = now_ms
            return [self._ack(seq, True), self._hello()]

        if type_ == P.ESTOP:
            self._latch_estop(str(msg.get("reason", "brain")), now_ms)
            return [self._ack(seq, True)]

        if type_ == P.RESET_ESTOP:
            return [self._reset_estop(seq, now_ms)]

        if type_ == P.HB:
            self.last_hb_ms = now_ms
            return [self._ack(seq, True)] if msg.get("ack") else []

        if type_ == P.STOP:
            self.target_l = self.target_r = 0
            self.cmd_expiry_ms = now_ms
            return [self._ack(seq, True)]

        if type_ in (P.VEL, P.MOTION):
            if self.estop:
                return [self._ack(seq, False, P.E_ESTOP_LATCHED)]
            if not self.handshaken:
                return [self._ack(seq, False, P.E_SCHEMA, "no hello yet")]
            self.last_hb_ms = now_ms          # any command proves the link is alive
            if type_ == P.VEL:
                self.target_l = int(msg.get("l", 0))
                self.target_r = int(msg.get("r", 0))
                ttl = min(int(msg.get("ttl", self.cfg.cmd_ttl_default_ms)), self.cfg.cmd_ttl_max_ms)
            else:
                self.target_l, self.target_r = self._mix(msg)
                ttl = min(int(msg.get("ms", 500)), self.cfg.max_motion_ms)
            self.cmd_expiry_ms = now_ms + ttl
            return [self._ack(seq, True)]

        # Expression commands: accepted, and outside the scope of this
        # simulator. The firmware routes them to the servo, LEDs and display.
        if type_ in (P.LOOK, P.GESTURE, P.LID, P.FACE, P.LEDS, P.CLIP, P.PCM, P.PCM_STOP, P.LIMITS):
            if type_ == P.LIMITS:
                self._lower_ceilings(msg)
            return [self._ack(seq, True)]

        self.rejected += 1
        return [self._ack(seq, False, P.E_SCHEMA, f"unknown type {type_!r}")]

    # ------------------------------------------------------------------
    # The loop
    # ------------------------------------------------------------------
    def tick(self, now_ms: int) -> None:
        self.now_ms = now_ms
        want_l, want_r = self.target_l, self.target_r
        inhibit = INHIBIT_NONE

        if self.estop:
            inhibit, want_l, want_r = INHIBIT_ESTOP, 0, 0
        elif self.battery_mv is not None and self.battery_mv < self.cfg.battery_critical_mv:
            inhibit, want_l, want_r = INHIBIT_BATTERY, 0, 0
        elif self.last_hb_ms is None or now_ms - self.last_hb_ms > self.cfg.link_timeout_ms:
            inhibit, want_l, want_r = INHIBIT_LINK, 0, 0
        else:
            if now_ms >= self.cmd_expiry_ms:
                want_l = want_r = 0
            if not self.motion_ok(now_ms):
                want_l, want_r, inhibit = self._escape_only(want_l, want_r, now_ms)

        if inhibit in (INHIBIT_ESTOP, INHIBIT_LINK, INHIBIT_BATTERY):
            self.duty_l = self.duty_r = 0            # hard stop: the ramp is bypassed
            self.target_l = self.target_r = 0
        else:
            self._ramp_to(want_l, want_r, now_ms)

        if inhibit != self.inhibit:
            self.events.append({"code": "INHIBIT", "text": inhibit or "clear", "t": now_ms})
        self.inhibit = inhibit

    # ------------------------------------------------------------------
    def _escape_only(self, want_l: int, want_r: int, now_ms: int) -> tuple[int, int, str]:
        """MOTION_OK is absent: forward is blocked, a short reverse is allowed."""
        forward = (want_l + want_r) > 0
        reversing = want_l < 0 and want_r < 0
        esc = self._escape

        if forward or not reversing:
            if esc.started_ms is not None:
                esc.last_end_ms = now_ms
                esc.started_ms = None
            return 0, 0, INHIBIT_MOTION_OK

        if esc.started_ms is None:
            cooling = (esc.last_end_ms is not None
                       and now_ms - esc.last_end_ms < self.cfg.escape_cooldown_ms)
            if cooling:
                return 0, 0, INHIBIT_MOTION_OK
            esc.started_ms = now_ms
        elif now_ms - esc.started_ms >= self.cfg.escape_ms:
            esc.started_ms = None
            esc.last_end_ms = now_ms
            return 0, 0, INHIBIT_MOTION_OK

        cap = self.cfg.escape_duty_pct
        return max(want_l, -cap), max(want_r, -cap), INHIBIT_MOTION_OK

    def _ramp_to(self, want_l: int, want_r: int, now_ms: int) -> None:
        if self._last_tick_ms is not None and now_ms - self._last_tick_ms < self.cfg.tick_ms:
            return
        self._last_tick_ms = now_ms
        ceiling = self.auto_max_pct
        self.duty_l = _step(self.duty_l, _clamp(want_l, ceiling), self.cfg)
        self.duty_r = _step(self.duty_r, _clamp(want_r, ceiling), self.cfg)

    def _mix(self, msg: dict[str, Any]) -> tuple[int, int]:
        speed = int(msg.get("speed", self.auto_max_pct))
        table = {
            "STOP": (0, 0),
            "MOVE_FORWARD": (1, 1),
            "MOVE_BACKWARD": (-1, -1),
            "TURN_LEFT": (-1, 1),
            "TURN_RIGHT": (1, -1),
            "ROTATE": (1, -1),
        }
        l, r = table.get(str(msg.get("cmd")), (0, 0))
        return l * speed, r * speed

    def _lower_ceilings(self, msg: dict[str, Any]) -> None:
        """The link may lower a ceiling. There is no message that raises one."""
        auto = int(msg.get("auto_max", self.auto_max_pct))
        if 0 < auto < self.auto_max_pct:
            self.auto_max_pct = auto

    def _latch_estop(self, reason: str, now_ms: int) -> None:
        if not self.estop:
            self.estop = True
            self.estop_reason = reason
            self.duty_l = self.duty_r = 0
            self.target_l = self.target_r = 0
            self.events.append({"code": "ESTOP", "text": reason, "t": now_ms})

    def _reset_estop(self, seq: int, now_ms: int) -> dict[str, Any]:
        if not self.estop:
            return self._ack(seq, True)
        if not self.estop_contact_closed:
            return self._ack(seq, False, P.E_ESTOP_LATCHED, "hardware button still pressed")
        if self.duty_l or self.duty_r:
            return self._ack(seq, False, P.E_BUSY, "motors not at zero")
        self.estop = False
        self.estop_reason = ""
        self.target_l = self.target_r = 0
        self.cmd_expiry_ms = now_ms          # nothing moves until a fresh command
        self.events.append({"code": "ESTOP_RESET", "text": "cleared by operator", "t": now_ms})
        return self._ack(seq, True)

    # ------------------------------------------------------------------
    def _ack(self, seq: int, ok: bool, err: str = "", detail: str = "") -> dict[str, Any]:
        # ack_seq, not seq: the envelope's own seq belongs to this ack.
        # The firmware (firmware/DustEBody/src/link/brainLink.cpp) does the same.
        fields: dict[str, Any] = {"ack_seq": seq, "ok": ok}
        if err:
            fields["err"] = err
        if detail:
            fields["detail"] = detail
        return self._framer.build(P.ACK, self.now_ms, **fields)

    def _hello(self) -> dict[str, Any]:
        return self._framer.build(
            P.HELLO, self.now_ms, fw="simbody",
            limits={"auto_max": self.auto_max_pct, "manual_max": self.cfg.manual_max_pct,
                    "ttl_max": self.cfg.cmd_ttl_max_ms},
            hw={"motors": "configured", "lid_servo": "configured", "leds": "configured",
                "tof_throat": "not_installed", "speaker": "not_installed",
                "battery": "not_instrumented" if self.battery_mv is None else "online"})

    def telemetry(self) -> dict[str, Any]:
        return self._framer.build(
            P.TELEMETRY, self.now_ms,
            ml=self.duty_l, mr=self.duty_r, tl=self.target_l, tr=self.target_r,
            estop=self.estop, estop_reason=self.estop_reason, inhibit=self.inhibit,
            motion_ok=self.motion_ok(self.now_ms),
            battery_mv=self.battery_mv,
            link={"crc_err": self.crc_errors, "rejected": self.rejected})

    @property
    def moving(self) -> bool:
        return self.duty_l != 0 or self.duty_r != 0


def _clamp(value: int, ceiling: int) -> int:
    return max(-ceiling, min(ceiling, int(value)))


def _step(current: int, target: int, cfg: BodyConfig) -> int:
    """One ramp step. Slowing down may always outrun speeding up."""
    accel = cfg.accel_pct_per_tick
    step = accel if abs(target) > abs(current) else accel * cfg.decel_mult
    diff = target - current
    if -step <= diff <= step:
        return target
    return current + (step if diff > 0 else -step)
