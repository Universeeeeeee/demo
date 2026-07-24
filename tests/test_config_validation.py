"""Unified runtime configuration validation tests."""

from __future__ import annotations

from config.config_validation import validate_runtime_config
from config.test_config import TestConfig as RuntimeTestConfig, default_jump_config
from config.treadmill_config import TreadmillGaitConfig


def test_default_supported_configs_pass_final_validation():
    treadmill = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.0,
        direction="Opposite side",
    )

    assert validate_runtime_config(default_jump_config()) == []
    assert validate_runtime_config(treadmill) == []


def test_missing_jump_count_and_unimplemented_trigger_are_rejected():
    config = RuntimeTestConfig(
        stop_type="Status change",
        number_of_jumps=None,
        start_type="External impulse",
    )

    errors = validate_runtime_config(config)

    assert any("目标跳跃次数" in error for error in errors)
    assert any("External impulse" in error for error in errors)
