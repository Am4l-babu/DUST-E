"""
link.py - the brain's live connection to the XIAO body.

Three layers, on purpose:

    Transport   raw bytes in, raw bytes out. `SerialTransport` wraps pyserial
                for the real USB link; `LoopbackPipe` is an in-memory stand-in
                so the whole stack - Validator, Framer, protocol.encode, the
                wire, LineReader, protocol.decode - can be exercised in a test
                with no board attached, wired directly to `simbody.SimBody`.

    BodyLink    owns one Transport. Every outbound command goes through the
                Validator before it is framed, so a bug upstream (nav sending
                `src="llm"`, or a stray raw wheel-speed dict) is caught here,
                not on the wire. Every inbound message updates `BodyState`.

    BodyState   what the brain currently believes about the body: the last
                telemetry, whether the hardware handshake succeeded, and -
                critically - whether any of that is still fresh. `online`
                answers "can I trust this", not "did I ever hear from it".

Nothing here decides whether the robot MAY move. That is the XIAO's reflex
layer. This module can be wrong about what it thinks is true; it cannot make
the robot do anything unsafe, because the validator still enforces source
policy and the body still enforces its own limits regardless of what it is told.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..config import BodyConfig
from . import protocol as P
from .validator import CommandRejected, Validator

log = logging.getLogger(__name__)


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...
    def read_available(self) -> bytes: ...
    def close(self) -> None: ...


class SerialTransport:
    """pyserial, non-blocking. The real link, over the powered USB hub."""

    def __init__(self, port: str, baud: int = 115200) -> None:
        import serial  # imported lazily: the rest of this module needs no dependency

        self._ser = serial.Serial(port, baud, timeout=0)

    def write(self, data: bytes) -> None:
        self._ser.write(data)

    def read_available(self) -> bytes:
        n = self._ser.in_waiting
        return self._ser.read(n) if n else b""

    def close(self) -> None:
        self._ser.close()


class LoopbackPipe:
    """An in-memory duplex byte pipe: what BodyLink writes, the other end reads.

    Used to test the full brain-side stack against `simbody.SimBody` with no
    serial port at all - see tests/test_body_link.py. Also usable as a manual
    "no board yet" debug transport, which is why it is not buried in tests/.
    """

    def __init__(self) -> None:
        self._to_peer = bytearray()
        self._to_self = bytearray()

    def write(self, data: bytes) -> None:
        self._to_peer.extend(data)

    def read_available(self) -> bytes:
        out = bytes(self._to_self)
        del self._to_self[:]
        return out

    def close(self) -> None:
        pass

    # --- the "peer" side, driven by whatever is standing in for the body ---
    def peer_read_available(self) -> bytes:
        out = bytes(self._to_peer)
        del self._to_peer[:]
        return out

    def peer_write(self, data: bytes) -> None:
        self._to_self.extend(data)


@dataclass
class BodyState:
    handshaken: bool = False
    fw_version: str = ""
    hw: dict[str, str] = field(default_factory=dict)
    limits: dict[str, int] = field(default_factory=dict)

    telemetry: dict[str, Any] = field(default_factory=dict)
    telemetry_at: float | None = None

    estop: bool = False
    estop_reason: str = ""
    inhibit: str = ""
    motion_ok: bool = False
    battery_mv: int | None = None

    events: list[dict[str, Any]] = field(default_factory=list)   # ring, trimmed by BodyLink
    crc_errors: int = 0
    rejected_local: int = 0     # rejected by OUR validator, before ever reaching the wire

    def online(self, now: float, stale_after_s: float) -> bool:
        """Trustworthy, not merely 'has ever connected'. A body gone silent
        for longer than the reflex layer's own link timeout is not online,
        even if the last thing it said was cheerful."""
        return self.telemetry_at is not None and (now - self.telemetry_at) < stale_after_s


class BodyLink:
    def __init__(self, transport: Transport, cfg: BodyConfig,
                 now_fn=time.monotonic, event_ring: int = 64) -> None:
        self._transport = transport
        self.cfg = cfg          # read-only reference for callers (e.g. body_probe)
        self._cfg = cfg
        self._now_fn = now_fn
        self._validator = Validator(cfg)
        self._framer = P.Framer()
        self._reader = P.LineReader()
        self._event_ring = event_ring
        self._last_hb_sent = 0.0
        self._last_hello_sent: float | None = None   # None = never attempted -> send immediately
        self.hello_retry_ms = cfg.heartbeat_ms * 10   # generous: hello is cheap, not urgent

        self.state = BodyState()

        # A rolling trace of both directions, for a DEBUG view - not the wire
        # bytes themselves (those are gone once framed/parsed), the decoded
        # message plus which way it went. Bounded so a dashboard left open
        # overnight does not grow this without limit.
        self.wire_log: list[dict[str, Any]] = []
        self._wire_log_ring = 200

    # ------------------------------------------------------------------
    def tick(self, now_ms: int) -> list[dict[str, Any]]:
        """Call every brain loop pass. Sends a heartbeat if due, drains the
        transport, updates state, and returns every inbound message decoded
        this pass (for logging; BodyState already reflects them)."""
        if not self.state.handshaken and (self._last_hello_sent is None
                                          or now_ms - self._last_hello_sent >= self.hello_retry_ms):
            self.hello(now_ms)     # first attempt, or a retry after a body reset

        if now_ms - self._last_hb_sent >= self._cfg.heartbeat_ms:
            self._last_hb_sent = now_ms
            self._send_raw(P.HB, now_ms, ack=False)

        chunk = self._transport.read_available()
        if not chunk:
            return []
        out: list[dict[str, Any]] = []
        for item in self._reader.feed(chunk):
            if isinstance(item, P.ProtocolError):
                if item.code == P.E_CRC:
                    self.state.crc_errors += 1
                log.warning("body link: %s", item)
                self._log_wire("rx_error", now_ms, code=item.code, detail=str(item))
                continue
            self._apply(item, now_ms)
            self._log_wire("rx", now_ms, **item)
            out.append(item)
        return out

    def hello(self, now_ms: int) -> None:
        self._last_hello_sent = now_ms
        self._send_raw(P.HELLO, now_ms)

    # ------------------------------------------------------------------
    def send(self, type_: str, src: str, now_ms: int, **fields: Any) -> bool:
        """Validate, clamp, frame, write. False means the validator refused
        it - the caller's bug, not the robot's problem."""
        msg = {"type": type_, "src": src, **fields}
        try:
            validated = self._validator.validate(msg, now_ms)
        except CommandRejected as e:
            self.state.rejected_local += 1
            log.warning("body link: local command rejected: %s", e)
            return False
        validated.pop("type", None)
        self._send_raw(type_, now_ms, **validated)
        return True

    def estop(self, reason: str, src: str, now_ms: int) -> bool:
        return self.send(P.ESTOP, src, now_ms, reason=reason)

    def stop(self, src: str, now_ms: int) -> bool:
        return self.send(P.STOP, src, now_ms)

    def velocity(self, left_pct: int, right_pct: int, now_ms: int,
                 ttl_ms: int | None = None, src: str = "nav") -> bool:
        fields: dict[str, Any] = {"l": left_pct, "r": right_pct}
        if ttl_ms is not None:
            fields["ttl"] = ttl_ms
        return self.send(P.VEL, src, now_ms, **fields)

    def close(self) -> None:
        self._transport.close()

    # ------------------------------------------------------------------
    def _send_raw(self, type_: str, now_ms: int, **fields: Any) -> None:
        self._transport.write(self._framer.line(type_, now_ms, **fields))
        self._log_wire("tx", now_ms, type=type_, **fields)

    def _log_wire(self, direction: str, now_ms: int, **fields: Any) -> None:
        self.wire_log.append({"dir": direction, "t": now_ms, **fields})
        if len(self.wire_log) > self._wire_log_ring:
            del self.wire_log[: len(self.wire_log) - self._wire_log_ring]

    def _apply(self, msg: dict[str, Any], now_ms: int) -> None:
        s = self.state
        t = msg.get("type")

        if t == P.HELLO:
            s.handshaken = True
            s.telemetry_at = None     # a fresh hello means the old telemetry predates a reset
            s.fw_version = msg.get("fw", "")
            s.hw = dict(msg.get("hw", {}))
            s.limits = dict(msg.get("limits", {}))
            return

        if t == P.TELEMETRY:
            s.telemetry = msg
            s.telemetry_at = self._now_fn()
            s.estop = bool(msg.get("estop", False))
            s.estop_reason = msg.get("estop_reason", "")
            s.inhibit = msg.get("inhibit", "")
            s.motion_ok = bool(msg.get("motion_ok", False))
            s.battery_mv = msg.get("battery_mv")
            return

        if t == P.EVENT:
            s.events.append(msg)
            if len(s.events) > self._event_ring:
                del s.events[: len(s.events) - self._event_ring]
            return

        # ACKs are informational here; a rejected command already logged
        # itself on the body side and the next telemetry tick shows the
        # consequence (e.g. inhibit staying non-empty). Nothing to update.
