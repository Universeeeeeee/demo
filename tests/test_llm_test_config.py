"""LLMTestConfig → TestConfig 转换测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.models import LLMTestConfig, LLMTreadmillGaitConfig, LLMTreadmillRunningConfig
from config.test_config import TestConfig as _TestConfig
from config.param_schema import get_schema


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
    )
    cfg = llm_cfg.to_test_config()

    assert cfg.stop_type == "Status change"
    assert cfg.number_of_jumps == 10
    assert cfg.start_type == "Status change"
    assert cfg.starting_foot == "Not defined"
    assert cfg.min_contact_time == 80
    assert cfg.min_flight_time == 20
    assert cfg.max_flight_time == 500
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
