"""
protocol.py - the wire format between the UNO Q and the XIAO ESP32-S3.

One JSON object per line with a CRC suffix:

    {"v":1,"seq":1042,"t":583211,"type":"vel","l":35,"r":31,"ttl":300}*7A3F

Chosen over a binary frame for one reason: it stays readable in a serial
monitor. When the robot drives into a wall at a demo, the fix has to be
visible in a terminal, not in a decoder ring. The CRC is there because USB
serial lines share a cable with motor wiring and do get corrupted; a bad line
is dropped and counted, never guessed at.

The reader tolerates the boot log and any other non-JSON noise on the same
port, because the ESP32 ROM prints on it and there is no way to stop that.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

PROTOCOL_VERSION = 1
MAX_LINE_BYTES = 4096


# --- message types: brain -> body ------------------------------------------
HELLO = "hello"
HB = "hb"
VEL = "vel"
MOTION = "motion"
STOP = "stop"
ESTOP = "estop"
RESET_ESTOP = "reset_estop"
LIMITS = "limits"
LOOK = "look"
GESTURE = "gesture"
LID = "lid"
FACE = "face"
LEDS = "leds"
CLIP = "clip"
PCM = "pcm"
PCM_STOP = "pcm_stop"

# --- message types: body -> brain ------------------------------------------
TELEMETRY = "telemetry"
ACK = "ack"
EVENT = "event"

# --- error codes (also used by the validator) ------------------------------
E_CRC = "E_CRC"
E_VERSION = "E_VERSION"
E_SCHEMA = "E_SCHEMA"
E_RANGE = "E_RANGE"
E_ESTOP_LATCHED = "E_ESTOP_LATCHED"
E_INHIBITED = "E_INHIBITED"
E_NOT_INSTALLED = "E_NOT_INSTALLED"
E_BUSY = "E_BUSY"
E_RATE = "E_RATE"
E_SRC_FORBIDDEN = "E_SRC_FORBIDDEN"


class ProtocolError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE. Check value for b"123456789" is 0x29B1."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode(msg: dict[str, Any]) -> bytes:
    """One message as a complete line, CRC included."""
    body = json.dumps(msg, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return b"%s*%04X\n" % (body, crc16_ccitt(body))


def decode(line: str | bytes) -> dict[str, Any]:
    """Parse one line. Raises ProtocolError; never returns a partial message."""
    raw = line.encode("utf-8") if isinstance(line, str) else bytes(line)
    raw = raw.strip()
    if not raw:
        raise ProtocolError(E_SCHEMA, "empty line")
    star = raw.rfind(b"*")
    if star < 0 or len(raw) - star != 5:
        raise ProtocolError(E_SCHEMA, "missing or malformed CRC suffix")
    body, crc_text = raw[:star], raw[star + 1:]
    try:
        want = int(crc_text, 16)
    except ValueError:
        raise ProtocolError(E_SCHEMA, "CRC is not hex") from None
    got = crc16_ccitt(body)
    if got != want:
        raise ProtocolError(E_CRC, f"computed {got:04X}, line says {want:04X}")
    try:
        msg = json.loads(body)
    except json.JSONDecodeError as e:
        raise ProtocolError(E_SCHEMA, f"bad JSON: {e.msg}") from None
    if not isinstance(msg, dict):
        raise ProtocolError(E_SCHEMA, "top level is not an object")
    if not isinstance(msg.get("type"), str):
        raise ProtocolError(E_SCHEMA, "no type")
    v = msg.get("v")
    if v is not None and v != PROTOCOL_VERSION:
        raise ProtocolError(E_VERSION, f"peer speaks v{v}, this is v{PROTOCOL_VERSION}")
    return msg


class LineReader:
    """Byte stream in, messages out. Survives split lines and boot-log noise."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self.dropped_noise = 0
        self.dropped_overlong = 0

    def feed(self, chunk: bytes) -> Iterator[dict[str, Any] | ProtocolError]:
        """Yields a dict per good message and a ProtocolError per bad one.

        Errors are yielded rather than raised: one corrupted line must not
        stop the stream, and the count of them is a diagnostic worth having.
        """
        self._buf.extend(chunk)
        while True:
            nl = self._buf.find(b"\n")
            if nl < 0:
                if len(self._buf) > MAX_LINE_BYTES:
                    self._buf.clear()
                    self.dropped_overlong += 1
                return
            line = bytes(self._buf[:nl])
            del self._buf[:nl + 1]
            stripped = line.strip()
            if not stripped:
                continue
            if not stripped.startswith(b"{"):
                self.dropped_noise += 1      # boot log, printf debugging, etc.
                continue
            try:
                yield decode(stripped)
            except ProtocolError as e:
                yield e


class Framer:
    """Adds the envelope: version, sequence number, sender timestamp."""

    def __init__(self) -> None:
        self.seq = 0

    def build(self, type_: str, now_ms: int, **fields: Any) -> dict[str, Any]:
        self.seq += 1
        msg: dict[str, Any] = {"v": PROTOCOL_VERSION, "seq": self.seq, "t": int(now_ms), "type": type_}
        msg.update(fields)
        return msg

    def line(self, type_: str, now_ms: int, **fields: Any) -> bytes:
        return encode(self.build(type_, now_ms, **fields))
