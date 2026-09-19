"""
Integration tests for the full brain-side stack against the body reference.

Every layer runs for real here: Validator -> Framer -> protocol.encode -> the
wire (a LoopbackPipe, not a mock) -> protocol.decode -> SimBody.handle() ->
protocol.encode -> the wire -> protocol.decode -> BodyState. Nothing is
patched or stubbed. If this suite passes and the firmware matches simbody.py
(brain/tests/test_simbody.py, and firmware/DustEBody/README.md section 4),
the brain's serial client is exercising the same protocol the real XIAO speaks.

No serial port, no XIAO, is involved - see BodyLink docstring for why that is
a deliberate layering, not a shortcut.
"""

from __future__ import annotations

import pytest

from dustebrain.body import protocol as P
from dustebrain.body.link import BodyLink, LoopbackPipe
from dustebrain.body.simbody import SimBody


class Harness:
    """Pumps a LoopbackPipe between a real BodyLink and a real SimBody."""

    def __init__(self, cfg):
        self.pipe = LoopbackPipe()
        self.link = BodyLink(self.pipe, cfg.body, now_fn=lambda: self.now_s)
        self.body = SimBody(cfg.body)
        self.now_s = 0.0
        self._last_telemetry_push = 0

    def step(self, now_ms: int, *, motion_ok: bool = True, telemetry_every_ms: int = 50,
             velocity: tuple[int, int] | None = None, velocity_src: str = "nav") -> None:
        self.now_s = now_ms / 1000.0

        # A real navigation loop resends its intent continuously - that is
        # what a command TTL is FOR. One-shot sends are exercised separately
        # (see test_a_velocity_command_expires_on_its_own in test_simbody.py);
        # here `velocity` models the steady-state "keep driving" case.
        if velocity is not None:
            self.link.velocity(velocity[0], velocity[1], now_ms, src=velocity_src)

        incoming = self.pipe.peer_read_available()
        if incoming:
            for reply in self.body.feed(incoming, now_ms):
                self.pipe.peer_write(P.encode(reply))

        if motion_ok:
            self.body.motion_ok_edge(now_ms)
        self.body.tick(now_ms)

        if now_ms - self._last_telemetry_push >= telemetry_every_ms:
            self._last_telemetry_push = now_ms
            self.pipe.peer_write(P.encode(self.body.telemetry()))

        self.link.tick(now_ms)

    def run(self, start_ms: int, duration_ms: int, step_ms: int = 20, **kw) -> int:
        t = start_ms
        end = start_ms + duration_ms
        while t <= end:
            self.step(t, **kw)
            t += step_ms
        return t


@pytest.fixture
def h(cfg):
    return Harness(cfg)


# ---------------------------------------------------------------------------
def test_handshake_completes_over_the_wire(h):
    assert not h.link.state.handshaken
    h.run(0, 200)
    assert h.link.state.handshaken
    assert h.link.state.fw_version == "simbody"
    assert h.link.state.limits.get("auto_max") == h.body.cfg.auto_max_pct
    assert h.link.state.hw.get("motors") == "configured"


def test_hello_is_retried_until_the_body_answers(h):
    """The brain keeps offering a hello; it does not give up after one try."""
    h.link.hello_retry_ms = 40
    # Advance the brain link WITHOUT pumping the body: prove more than one
    # hello goes out, then let the body answer and confirm it still completes.
    for t in (0, 20, 40, 60, 80):
        h.link.tick(t)
    assert not h.link.state.handshaken
    sent = h.pipe.peer_read_available()
    assert sent.count(b'"type":"hello"') >= 2
    h.run(100, 200)
    assert h.link.state.handshaken


def test_heartbeats_and_telemetry_flow_both_ways(h):
    h.run(0, 300)
    assert h.link.state.telemetry_at is not None
    assert h.link.state.inhibit == ""          # healthy: linked, motion_ok, no estop
    assert h.body.received > 0                 # the body actually saw our heartbeats
    assert h.link.state.telemetry.get("motion_ok") is True


def test_a_velocity_command_reaches_the_body_and_moves_it(h):
    h.run(0, 100)
    h.run(120, 600, velocity=(100, 100))   # resent every step, like a real nav loop
    assert h.body.moving
    assert h.body.duty_l == h.body.auto_max_pct     # clamped by the validator AND the body


def test_the_llm_cannot_drive_the_wheels_even_with_a_live_link(h):
    h.run(0, 100)
    ok = h.link.send(P.VEL, "llm", 120, l=40, r=40)
    assert ok is False
    assert h.link.state.rejected_local == 1
    assert b'"type":"vel"' not in h.pipe.peer_read_available()    # never even reached the wire
    h.run(120, 300)
    assert not h.body.moving


def test_estop_over_the_wire_stops_a_moving_body(h):
    h.run(0, 100)
    h.run(120, 400, velocity=(40, 40))
    assert h.body.moving

    assert h.link.estop("dashboard", "manual", 540)
    h.run(560, 200, velocity=(40, 40))     # even a nav loop that keeps insisting...
    assert not h.body.moving               # ...does not get through a latched estop
    assert h.link.state.estop is True
    assert h.link.state.estop_reason == "dashboard"


def test_only_manual_may_clear_the_estop_and_it_propagates_back(h):
    h.run(0, 100)
    h.link.estop("test", "safety", 120)
    h.run(140, 200)
    assert h.link.state.estop is True

    assert h.link.send(P.RESET_ESTOP, "nav", 360) is False    # validator refuses locally
    h.run(380, 200)
    assert h.link.state.estop is True                          # unchanged: never sent

    assert h.link.send(P.RESET_ESTOP, "manual", 600)
    h.run(620, 200)
    assert h.link.state.estop is False


def test_ceiling_can_be_lowered_over_the_wire_and_stays_lowered(h):
    h.run(0, 100)
    assert h.link.send(P.LIMITS, "manual", 120, auto_max=15)
    h.run(140, 600, velocity=(100, 100))
    assert h.body.duty_l == 15

    # An attempted raise is accepted as a message but has no effect - same
    # rule as the validator's own unit test, now proven end to end.
    assert h.link.send(P.LIMITS, "manual", 760, auto_max=90)
    h.run(780, 600, velocity=(100, 100))
    assert h.body.duty_l == 15


def test_a_reset_body_is_not_trusted_on_stale_telemetry(h):
    h.run(0, 300)
    assert h.link.state.online(h.now_s, stale_after_s=1.0)

    # Body sends an unsolicited hello (a reboot mid-session) with no
    # telemetry following it yet.
    h.pipe.peer_write(P.encode(h.body._hello()))
    h.link.tick(320)
    assert h.link.state.handshaken
    assert not h.link.state.online(320 / 1000.0, stale_after_s=1.0)


def test_online_goes_false_when_telemetry_stops_arriving(h):
    h.run(0, 300, telemetry_every_ms=50)
    assert h.link.state.online(h.now_s, stale_after_s=0.5)
    h.run(320, 700, telemetry_every_ms=10_000)      # telemetry effectively stops
    assert not h.link.state.online(h.now_s, stale_after_s=0.5)


def test_corrupted_bytes_on_the_wire_are_counted_and_do_not_wedge_the_link(h):
    h.run(0, 100)
    good = P.encode(h.body.telemetry())
    corrupted = good.replace(b'"estop":false', b'"estop":true!')
    h.pipe.peer_write(corrupted)
    h.link.tick(120)
    assert h.link.state.crc_errors == 1

    h.pipe.peer_write(P.encode(h.body.telemetry()))
    h.link.tick(140)
    assert h.link.state.telemetry_at is not None   # the stream recovered
