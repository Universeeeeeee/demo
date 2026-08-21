"""规则引擎单元测试 — 覆盖单条/多条规则叠加、边界值、保守聚合策略"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.rule_engine import RuleEngine, PROFILE_RULES
from agent.models import AthleteProfile
from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig


def _configure(age, level, **kwargs):
    ctx = AthleteProfile(age=age, weight=70, height=170, level=level, **kwargs)
    return RuleEngine().configure("Jump Test", ctx)


# ── 单条规则匹配 ──

def test_elderly_rule():
    """年长用户 (>60): min_contact_time=80, number_of_jumps=3"""
    config = _configure(age=65, level="intermediate")
    assert config.min_contact_time == 80
    assert config.number_of_jumps == 3
    assert config.max_flight_time == 0        # 规则未覆盖，保持默认值
    assert config.stop_type == "Status change"  # 规则未覆盖，保持默认值


def test_child_rule():
    """儿童 (<12): min_contact_time=40, number_of_jumps=3"""
    config = _configure(age=10, level="intermediate")
    assert config.min_contact_time == 40
    assert config.number_of_jumps == 3


def test_beginner_rule():
    """入门用户: min_contact_time=100, number_of_jumps=3"""
    config = _configure(age=35, level="beginner")
    assert config.min_contact_time == 100
    assert config.number_of_jumps == 3


def test_beginner_baseline():
    """入门用户默认不叠加其他规则: min_contact_time=100, number_of_jumps=3"""
    config = _configure(age=35, level="beginner")
    assert config.min_contact_time == 100
    assert config.number_of_jumps == 3
    assert config.max_flight_time == 0


# ── 无规则匹配 ──

def test_intermediate_defaults():
    """进阶用户 (age=30): 不触发任何规则，全默认值"""
    config = _configure(age=30, level="intermediate")
    assert config.min_contact_time == 60     # 默认值
    assert config.number_of_jumps == 5       # 默认值: 5次
    assert config.max_flight_time == 0       # 默认禁用
    assert config.stop_type == "Status change"


# ── 边界值 ──

def test_age_60_edge():
    """age=60 不触发老年人规则 (60 不 > 60)"""
    config = _configure(age=60, level="intermediate")
    assert config.min_contact_time == 60     # 默认值，未被规则修改
    assert config.number_of_jumps == 5


def test_age_61_edge():
    """age=61 触发老年人规则"""
    config = _configure(age=61, level="intermediate")
    assert config.min_contact_time == 80
    assert config.number_of_jumps == 3


def test_age_12_edge():
    """age=12 不触发儿童规则 (12 不 < 12)"""
    config = _configure(age=12, level="intermediate")
    assert config.min_contact_time == 60     # 默认值


def test_age_11_edge():
    """age=11 触发儿童规则"""
    config = _configure(age=11, level="intermediate")
    assert config.min_contact_time == 40


# ── 多规则叠加：保守聚合 ──

def test_elderly_beginner_overlap():
    """age=65 + beginner: min_contact = max(80, 100) = 100, jumps = min(3, 3) = 3"""
    config = _configure(age=65, level="beginner")
    assert config.min_contact_time == 100    # 取最保守（最大值）
    assert config.number_of_jumps == 3


# ── 顺序无关性 ──

def test_order_independence():
    """交换 PROFILE_RULES 顺序后，相同输入应得到相同输出"""
    import agent.rule_engine as re

    ctx = AthleteProfile(age=65, weight=70, height=170, level="beginner")
    config_a = RuleEngine().configure("Jump Test", ctx)

    # 反转规则列表
    original = list(re.PROFILE_RULES)
    try:
        re.PROFILE_RULES[:] = original[::-1]
        config_b = RuleEngine().configure("Jump Test", ctx)
        assert config_a.min_contact_time == config_b.min_contact_time
        assert config_a.number_of_jumps == config_b.number_of_jumps
        assert config_a.max_flight_time == config_b.max_flight_time
    finally:
        re.PROFILE_RULES[:] = original


# ── 校验通过性 ──

def test_all_rules_produce_valid_config():
    """每条规则单独触发时，输出能通过 ParamSchema 校验"""
    from config.param_schema import get_schema

    schema = get_schema()
    test_cases = [
        ("年长用户", AthleteProfile(age=65, weight=70, height=170, level="intermediate")),
        ("儿童", AthleteProfile(age=10, weight=30, height=140, level="intermediate")),
        ("入门用户", AthleteProfile(age=35, weight=70, height=170, level="beginner")),
        ("进阶用户", AthleteProfile(age=30, weight=70, height=170, level="intermediate")),
        ("高阶用户", AthleteProfile(age=30, weight=70, height=170, level="advanced")),
        ("多规则", AthleteProfile(age=65, weight=70, height=170, level="beginner")),
    ]
    for name, ctx in test_cases:
        config = RuleEngine().configure("Jump Test", ctx)
        values = config.to_dict()
        values.setdefault("test_macro_type", "Performance")
        errors = schema.validate(config.test_type, values)
        assert not errors, f"{name}: {errors}"


def test_offline_rule_engine_supports_all_runtime_modes():
    ctx = AthleteProfile(age=30, weight=70, height=170, level="intermediate")
    engine = RuleEngine()

    gait = engine.configure("Treadmill Gait Test", ctx)
    running = engine.configure("Treadmill Running Test", ctx)

    assert isinstance(gait, TreadmillGaitConfig)
    assert gait.treadmill_speed == 3.0
    assert isinstance(running, TreadmillRunningConfig)
    assert running.treadmill_speed == 6.0


def test_offline_rule_engine_rejects_unknown_mode():
    ctx = AthleteProfile(age=30, weight=70, height=170, level="intermediate")

    import pytest

    with pytest.raises(ValueError, match="不支持的离线测试类型"):
        RuleEngine().configure("Unknown Test", ctx)


def test_profile_filter_policy_applies_to_treadmill_modes():
    ctx = AthleteProfile(age=65, weight=70, height=170, level="beginner")

    gait = RuleEngine().configure("Treadmill Gait Test", ctx)
    running = RuleEngine().configure("Treadmill Running Test", ctx)

    assert gait.min_contact_time == 100
    assert running.min_contact_time == 100
