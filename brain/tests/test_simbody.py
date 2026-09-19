"""
The failsafe matrix from docs/COMPANION_ARCHITECTURE.md section 8.1, as tests.

These run against the Python reference implementation of the body's reflex
safety. When the XIAO firmware exists, the same scenarios are pointed at the
real board over serial: if the firmware disagrees with any of these, the
firmware is wrong.
"""

import pytest

from dustebrain.body import protocol as P
from dustebrain.body.simbody import (
    INHIBIT_BATTERY,
    INHIBIT_ESTOP,
    INHIBIT_LINK,
    INHIBIT_MOTION_OK,
    INHIBIT_NONE,
    SimBody,
)


def make_body(cfg, t=0):
    body = SimBody(cfg.body)
    body.handle({"type": P.HELLO, "seq": 1}, t)
    return body


def run(body, cfg, start_ms, duration_ms, *, heartbeat=True, motion_ok=True, drive=None):
    """Advance time in tick steps, optionally keeping the link and sensors alive."""
    t = start_ms
    end = start_ms + duration_ms
    step = cfg.body.tick_ms
    while t <= end:
        if heartbeat and t % cfg.body.heartbeat_ms == 0:
            body.handle({"type": P.HB, "seq": t}, t)
        if motion_ok and t % 20 == 0:
            body.motion_ok_edge(t)
        if drive is not None and t % 100 == 0:
            body.handle({"type": P.VEL, "seq": t, "l": drive[0], "r": drive[1],
                         "ttl": cfg.body.cmd_ttl_default_ms}, t)
        body.tick(t)
        t += step
    return t


def test_it_drives_when_everything_is_healthy(cfg):
    body = make_body(cfg)
    run(body, cfg, 0, 500, drive=(40, 40))
    assert body.moving and body.inhibit == INHIBIT_NONE
    assert body.duty_l == min(40, cfg.body.auto_max_pct)


def test_brain_goes_quiet_and_the_motors_stop(cfg):
    body = make_body(cfg)
    t = run(body, cfg, 0, 500, drive=(40, 40))
    assert body.moving
    run(body, cfg, t, cfg.body.link_timeout_ms + 100, heartbeat=False, drive=None)
    assert not body.moving and body.inhibit == INHIBIT_LINK


def test_a_velocity_command_expires_on_its_own(cfg):
    body = make_body(cfg)
    t = run(body, cfg, 0, 400, drive=(40, 40))
    assert body.moving
    # Heartbeats continue - only the drive intent stops. The link is fine,
    # so this is a ramp to zero, not a fault.
    run(body, cfg, t, cfg.body.cmd_ttl_max_ms + 300, drive=None)
    assert not body.moving and body.inhibit == INHIBIT_NONE


def test_estop_latches_and_ignores_further_commands(cfg):
    body = make_body(cfg)
    t = run(body, cfg, 0, 400, drive=(40, 40))
    body.handle({"type": P.ESTOP, "seq": 99, "reason": "test"}, t)
    body.tick(t)
    assert not body.moving and body.inhibit == INHIBIT_ESTOP

    ack = body.handle({"type": P.VEL, "seq": 100, "l": 40, "r": 40, "ttl": 300}, t + 20)[0]
    assert ack["ok"] is False and ack["err"] == P.E_ESTOP_LATCHED
    run(body, cfg, t + 40, 500, drive=(40, 40))
    assert not body.moving


def test_estop_reset_requires_the_button_released(cfg):
    body = make_body(cfg)
    body.press_estop_button(100)
    body.tick(100)
    refused = body.handle({"type": P.RESET_ESTOP, "seq": 5}, 200)[0]
    assert refused["ok"] is False and refused["err"] == P.E_ESTOP_LATCHED

    body.release_estop_button()
    accepted = body.handle({"type": P.RESET_ESTOP, "seq": 6}, 300)[0]
    assert accepted["ok"] is True and not body.estop


def test_nothing_moves_immediately_after_a_reset(cfg):
    body = make_body(cfg)
    body.handle({"type": P.ESTOP, "seq": 2, "reason": "test"}, 100)
    body.tick(100)
    body.handle({"type": P.RESET_ESTOP, "seq": 3}, 200)
    run(body, cfg, 220, 400, drive=None)
    assert not body.moving          # a fresh command is required


def test_sensor_veto_blocks_forward_motion(cfg):
    body = make_body(cfg)
    run(body, cfg, 0, 600, motion_ok=False, drive=(40, 40))
    assert not body.moving and body.inhibit == INHIBIT_MOTION_OK


def test_sensor_veto_allows_a_short_slow_reverse_escape(cfg):
    body = make_body(cfg)
    run(body, cfg, 0, 300, motion_ok=False, drive=(-40, -40))
    assert body.moving and body.duty_l < 0
    assert abs(body.duty_l) <= cfg.body.escape_duty_pct     # crawl, not a bolt

    # ...and it must not become a habit: the escape expires by itself.
    run(body, cfg, 320, cfg.body.escape_ms + 200, motion_ok=False, drive=(-40, -40))
    assert not body.moving


def test_a_dead_sensor_node_looks_exactly_like_a_hazard(cfg):
    """A crashed MCU, a broken wire and a wall are all 'no pulses'."""
    body = make_body(cfg)
    t = run(body, cfg, 0, 400, drive=(40, 40))
    assert body.moving
    run(body, cfg, t, cfg.body.motion_ok_window_ms + 200, motion_ok=False, drive=(40, 40))
    assert not body.moving and body.inhibit == INHIBIT_MOTION_OK


def test_a_stuck_high_wire_is_not_mistaken_for_consent(cfg):
    """MOTION_OK is a pulse train precisely so a stuck level cannot pass."""
    body = make_body(cfg)
    body.motion_ok_edge(0)                    # one edge, then the wire sticks
    run(body, cfg, 20, 400, motion_ok=False, drive=(40, 40))
    assert not body.moving


def test_critical_battery_refuses_to_move(cfg):
    body = make_body(cfg)
    body.battery_mv = cfg.body.battery_critical_mv - 100
    run(body, cfg, 0, 500, drive=(40, 40))
    assert not body.moving and body.inhibit == INHIBIT_BATTERY


def test_speed_ceiling_is_enforced_below_any_request(cfg):
    body = make_body(cfg)
    run(body, cfg, 0, 800, drive=(100, 100))
    assert body.duty_l == cfg.body.auto_max_pct


def test_the_link_can_lower_a_ceiling_but_never_raise_it(cfg):
    body = make_body(cfg)
    body.handle({"type": P.LIMITS, "seq": 4, "auto_max": 20}, 0)
    run(body, cfg, 0, 800, drive=(100, 100))
    assert body.duty_l == 20
    body.handle({"type": P.LIMITS, "seq": 5, "auto_max": 100}, 900)
    run(body, cfg, 900, 800, drive=(100, 100))
    assert body.duty_l == 20


def test_acceleration_is_ramped_and_stopping_is_faster(cfg):
    body = make_body(cfg)
    body.handle({"type": P.VEL, "seq": 10, "l": 45, "r": 45, "ttl": 500}, 0)
    body.motion_ok_edge(0)
    body.motion_ok_edge(10)
    body.tick(0)
    assert body.duty_l == cfg.body.accel_pct_per_tick        # no instant jump
    ticks_up = 1
    t = cfg.body.tick_ms
    while body.duty_l < 45 and ticks_up < 100:
        body.motion_ok_edge(t)
        body.handle({"type": P.HB, "seq": t}, t)
        body.tick(t)
        t += cfg.body.tick_ms
        ticks_up += 1

    body.handle({"type": P.STOP, "seq": 11}, t)
    ticks_down = 0
    while body.duty_l > 0 and ticks_down < 100:
        body.motion_ok_edge(t)
        body.handle({"type": P.HB, "seq": t}, t)
        body.tick(t)
        t += cfg.body.tick_ms
        ticks_down += 1
    assert ticks_down < ticks_up


def test_a_corrupted_line_is_dropped_and_counted(cfg):
    body = make_body(cfg)
    good = P.encode({"v": 1, "seq": 20, "t": 0, "type": "vel", "l": 40, "r": 40, "ttl": 300})
    bad = good.replace(b'"l":40', b'"l":99')
    body.feed(bad, 0)
    assert body.crc_errors == 1 and body.target_l == 0     # not acted on, not guessed
    body.feed(good, 10)
    assert body.target_l == 40


def test_commands_before_the_handshake_are_refused(cfg):
    body = SimBody(cfg.body)                  # no hello
    ack = body.handle({"type": P.VEL, "seq": 1, "l": 40, "r": 40}, 0)[0]
    assert ack["ok"] is False
    run(body, cfg, 0, 400, drive=(40, 40))
    assert not body.moving
