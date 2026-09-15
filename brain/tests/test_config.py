import pytest

from binbrain.config import ConfigError, deep_merge, load_config


def test_defaults_load_and_validate(cfg):
    assert cfg.world.zones.bounds == (0.8, 1.5, 2.0, 3.0)
    assert cfg.detector.backend in ("opencv", "onnxruntime", "none")
    assert cfg.camera.source == "0"


def test_unknown_key_is_an_error_not_a_silent_default():
    with pytest.raises(ConfigError, match="unknown key"):
        load_config(overrides={"tracker": {"confirm_hit": 5}})


def test_wrong_type_is_rejected():
    with pytest.raises(ConfigError, match="expected int"):
        load_config(overrides={"tracker": {"confirm_hits": "three"}})
    with pytest.raises(ConfigError, match="expected bool"):
        load_config(overrides={"camera": {"flip_horizontal": 1}})


def test_zones_must_be_ordered():
    with pytest.raises(ConfigError, match="increase strictly"):
        load_config(overrides={"world": {"zones": {"interact_max_m": 2.5}}})


def test_hysteresis_cannot_swallow_a_zone():
    with pytest.raises(ConfigError, match="hysteresis"):
        load_config(overrides={"world": {"zones": {"hysteresis_m": 0.3}}})


def test_override_file_merges(tmp_path):
    p = tmp_path / "local.yaml"
    p.write_text("camera:\n  hfov_deg: 90\nworld:\n  zones:\n    notice_max_m: 3.5\n", encoding="utf-8")
    c = load_config(p)
    assert c.camera.hfov_deg == 90.0
    assert c.world.zones.notice_max_m == 3.5
    assert c.world.zones.too_close_m == 0.8        # untouched keys keep their defaults


def test_deep_merge_does_not_mutate_inputs():
    base = {"a": {"b": 1, "c": 2}}
    out = deep_merge(base, {"a": {"b": 9}})
    assert out == {"a": {"b": 9, "c": 2}}
    assert base == {"a": {"b": 1, "c": 2}}
