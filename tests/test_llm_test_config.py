"""LLMTestConfig → TestConfig 转换测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.models import LLMTestConfig, LLMTreadmillGaitConfig, LLMTreadmillRunningConfig
from config.test_config import TestConfig as _TestConfig
from config.param_schema import get_schema
from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig


def test_to_test_config_excludes_reply_message():
    """LLMTestConfig 的 reply_message 字段不应传递到 TestConfig"""
    llm_cfg = LLMTestConfig(
        reply_message="测试配置，忽略",
        stop_type="Status change",
        number_of_jumps=10,
        min_contact_time=80,
    )
    cfg = llm_cfg.to_test_config()
    assert isinstance(cfg, _TestConfig)
    assert not hasattr(cfg, "reply_message"), "reply_message 泄漏到 TestConfig"


def test_to_test_config_passes_shared_fields():
    """LLMTestConfig → TestConfig 共用字段应正确传递"""
    llm_cfg = LLMTestConfig(
        reply_message="摘要",
        stop_type="Status change",
        number_of_jumps=10,
        test_length=None,
        start_type="Status change",
        start_position="Inside area",
        starting_foot="Not defined",
        finish_position="Inside area",
        min_contact_time=80,
        min_flight_time=20,
        max_flight_time=500,
        flight_time_review_threshold=750,
    )
    cfg = llm_cfg.to_test_config()

    assert cfg.stop_type == "Status change"
    assert cfg.number_of_jumps == 10
    assert cfg.start_type == "Status change"
    assert cfg.starting_foot == "Not defined"
    assert cfg.min_contact_time == 80
    assert cfg.min_flight_time == 20
    assert cfg.max_flight_time == 500
    assert cfg.flight_time_review_threshold == 750
    assert cfg.test_length is None or cfg.test_length == "00:00"  # 取决于格式


def test_to_test_config_passes_validation():
    """通过 LLMTestConfig 转换后的配置应能通过 ParamSchema 校验"""
    llm_cfg = LLMTestConfig(
        reply_message="可忽略",
        stop_type="Status change",
        number_of_jumps=5,
        min_contact_time=60,
        max_flight_time=0,
    )
    cfg = llm_cfg.to_test_config()
    schema = get_schema()
    values = cfg.to_dict()
    values.setdefault("test_macro_type", "Performance")
    errors = schema.validate(cfg.test_type, values)
    assert not errors, f"校验不通过: {errors}"


def test_jump_review_threshold_is_configurable_and_jump_only():
    schema = get_schema()
    definition = schema.get_param_def("flight_time_review_threshold")

    assert definition is not None
    assert definition.default == 700
    assert definition.unit == "ms"
    jump_names = {
        item.name for item in schema.get_params_for_test("Jump Test")
    }
    treadmill_names = {
        item.name for item in schema.get_params_for_test("Treadmill Gait Test")
    }
    assert "flight_time_review_threshold" in jump_names
    assert "flight_time_review_threshold" not in treadmill_names


def test_to_test_config_none_excluded():
    """exclude_none=True 应排除 None 字段，避免覆盖 TestConfig 默认值"""
    llm_cfg = LLMTestConfig(
        reply_message="测试空值排除",
        finish_position="Inside area",  # Literal 字段不能为 None
    )
    cfg = llm_cfg.to_test_config()
    # 未显式 set 的值应使用 TestConfig 默认值
    assert cfg.min_contact_time == 60  # 默认正确


def test_to_test_config_with_exclude_none_preserves_defaults():
    """exclude_none=True 不应影响显式设置的字段"""
    llm_cfg = LLMTestConfig(
        reply_message="保持默认测试",
        stop_type="Status change",
        number_of_jumps=3,
        min_contact_time=100,
    )
    cfg = llm_cfg.to_test_config()
    assert cfg.stop_type == "Status change"
    assert cfg.number_of_jumps == 3
    assert cfg.min_contact_time == 100
    # 未显式设置的值应为 TestConfig 默认值
    assert cfg.start_type == "Status change"
    assert cfg.starting_foot == "Not defined"
    assert cfg.metronome_enabled is False


def test_jump_llm_config_does_not_accept_treadmill_speed():
    """LLMTestConfig schema 不应包含 treadmill 专属字段"""
    schema = LLMTestConfig.model_json_schema()
    assert "treadmill_speed" not in schema["properties"]


def test_treadmill_gait_llm_config_requires_speed_and_duration_or_manual_stop():
    """LLMTreadmillGaitConfig 应接受 treadmill 字段并自动设置 test_type"""
    cfg = LLMTreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        foot_length_cm_snapshot=26.0,
        foot_length_source="manual",
    )
    assert cfg.test_type == "Treadmill Gait Test"
    assert cfg.treadmill_speed == 5.0


def test_treadmill_gait_llm_config_defaults_to_walking_speed_and_opposite_direction():
    cfg = LLMTreadmillGaitConfig()

    assert cfg.treadmill_speed == 3.0
    assert cfg.direction == "Opposite side"


def test_treadmill_gait_to_test_config_excludes_test_type_discriminator():
    llm_cfg = LLMTreadmillGaitConfig(
        stop_type="End of Time",
        test_length="1min",
        treadmill_speed=3.0,
        direction="Opposite side",
    )

    cfg = llm_cfg.to_test_config()

    assert isinstance(cfg, TreadmillGaitConfig)
    assert cfg.test_type == "Treadmill Gait Test"
    assert cfg.test_length == "01:00"


def test_treadmill_running_llm_config_defaults_to_running_speed_and_opposite_direction():
    cfg = LLMTreadmillRunningConfig()

    assert cfg.treadmill_speed == 6.0
    assert cfg.direction == "Opposite side"


def test_treadmill_running_to_test_config_excludes_test_type_discriminator():
    llm_cfg = LLMTreadmillRunningConfig(
        stop_type="End of Time",
        test_length="1min",
        treadmill_speed=6.0,
        direction="Opposite side",
    )

    cfg = llm_cfg.to_test_config()

    assert isinstance(cfg, TreadmillRunningConfig)
    assert cfg.test_type == "Treadmill Running Test"
    assert cfg.stop_type == "End of Time"
    assert cfg.test_length == "01:00"
    assert cfg.treadmill_speed == 6.0
    assert cfg.direction == "Opposite side"


if __name__ == "__main__":
    tests = [
        test_to_test_config_excludes_reply_message,
        test_to_test_config_passes_shared_fields,
        test_to_test_config_passes_validation,
        test_to_test_config_none_excluded,
        test_to_test_config_with_exclude_none_preserves_defaults,
        test_jump_llm_config_does_not_accept_treadmill_speed,
        test_treadmill_gait_llm_config_requires_speed_and_duration_or_manual_stop,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  OK {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
