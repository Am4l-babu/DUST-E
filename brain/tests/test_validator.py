import pytest

from dustebrain.body import protocol as P
from dustebrain.body.validator import CommandRejected, Validator


@pytest.fixture
def v(cfg):
    return Validator(cfg.body)


def test_the_llm_cannot_ask_for_a_wheel_speed(v):
    with pytest.raises(CommandRejected) as e:
        v.validate({"type": P.VEL, "src": "llm", "l": 40, "r": 40}, 0)
    assert e.value.code == P.E_SRC_FORBIDDEN


def test_the_llm_can_ask_to_look_at_someone(v):
    out = v.validate({"type": P.LOOK, "src": "llm", "x": 0.3, "y": 0.0}, 0)
    assert out["x"] == pytest.approx(0.3)


def test_only_a_human_can_clear_an_emergency_stop(v):
    for src in ("nav", "llm", "social", "safety"):
        with pytest.raises(CommandRejected):
            v.validate({"type": P.RESET_ESTOP, "src": src}, 0)
    assert v.validate({"type": P.RESET_ESTOP, "src": "manual"}, 0)["type"] == P.RESET_ESTOP


def test_anyone_can_stop_the_robot(v):
    for src in ("nav", "llm", "social", "debug", "manual", "safety"):
        assert v.validate({"type": P.ESTOP, "src": src, "reason": "test"}, 0)


def test_autonomous_speed_is_capped_lower_than_manual(cfg, v):
    auto = v.validate({"type": P.VEL, "src": "nav", "l": 100, "r": 100}, 0)
    manual = v.validate({"type": P.VEL, "src": "manual", "l": 100, "r": 100}, 0)
    assert auto["l"] == cfg.body.auto_max_pct
    assert manual["l"] == cfg.body.manual_max_pct
    assert auto["l"] < manual["l"]


def test_ttl_is_clamped(cfg, v):
    out = v.validate({"type": P.VEL, "src": "nav", "l": 10, "r": 10, "ttl": 60_000}, 0)
    assert out["ttl"] == cfg.body.cmd_ttl_max_ms


def test_limits_can_only_be_lowered(cfg, v):
    v.validate({"type": P.LIMITS, "src": "manual", "auto_max": 20}, 0)
    assert v.ceilings.auto_max_pct == 20
    v.validate({"type": P.LIMITS, "src": "manual", "auto_max": 90}, 10)
    assert v.ceilings.auto_max_pct == 20          # the raise is ignored, not honoured
    assert v.validate({"type": P.VEL, "src": "nav", "l": 100, "r": 100}, 20)["l"] == 20


def test_unknown_types_and_enums_are_refused(v):
    with pytest.raises(CommandRejected) as e:
        v.validate({"type": "self_destruct", "src": "manual"}, 0)
    assert e.value.code == P.E_SCHEMA
    with pytest.raises(CommandRejected) as e:
        v.validate({"type": P.GESTURE, "src": "llm", "name": "MOONWALK"}, 0)
    assert e.value.code == P.E_RANGE


def test_non_numeric_velocity_is_refused_not_coerced(v):
    with pytest.raises(CommandRejected) as e:
        v.validate({"type": P.VEL, "src": "nav", "l": "fast", "r": 0}, 0)
    assert e.value.code == P.E_SCHEMA


def test_rate_limit_bites_but_never_on_a_stop(cfg, v):
    allowed = 0
    for _ in range(cfg.body.rate_limit_hz * 3):
        try:
            v.validate({"type": P.LOOK, "src": "nav", "x": 0.0, "y": 0.0}, 0)
            allowed += 1
        except CommandRejected as e:
            assert e.code == P.E_RATE
    assert allowed == cfg.body.rate_limit_hz
    for _ in range(200):
        assert v.validate({"type": P.ESTOP, "src": "nav"}, 0)


def test_tokens_refill_over_time(cfg, v):
    for _ in range(cfg.body.rate_limit_hz):
        v.validate({"type": P.LOOK, "src": "nav", "x": 0.0, "y": 0.0}, 0)
    with pytest.raises(CommandRejected):
        v.validate({"type": P.LOOK, "src": "nav", "x": 0.0, "y": 0.0}, 0)
    assert v.validate({"type": P.LOOK, "src": "nav", "x": 0.0, "y": 0.0}, 1000)
