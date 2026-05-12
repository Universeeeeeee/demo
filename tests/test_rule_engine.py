"""规则引擎单元测试 — 覆盖单条/多条规则叠加、边界值、保守聚合策略"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.rule_engine import RuleEngine, PATIENT_RULES
from agent.models import PatientContext


def _configure(age, condition, **kwargs):
    ctx = PatientContext(age=age, weight=70, height=170, condition=condition, **kwargs)
    return RuleEngine().configure("Jump Test", ctx)


# ── 单条规则匹配 ──

def test_elderly_rule():
    """老年人 (>60): min_contact_time=80, number_of_jumps=3"""
    config = _configure(age=65, condition="healthy")
    assert config.min_contact_time == 80
    assert config.number_of_jumps == 3
    assert config.max_flight_time == 0        # 规则未覆盖，保持默认值
    assert config.stop_type == "Status change"  # 规则未覆盖，保持默认值


def test_child_rule():
    """儿童 (<12): min_contact_time=40, number_of_jumps=3"""
    config = _configure(age=10, condition="healthy")
    assert config.min_contact_time == 40
    assert config.number_of_jumps == 3


def test_post_surgery_rule():
    """术后康复: min_contact_time=100, number_of_jumps=3"""
    config = _configure(age=35, condition="post_surgery")
    assert config.min_contact_time == 100
    assert config.number_of_jumps == 3


def test_neurological_rule():
    """神经系统疾病: min_contact_time=100, number_of_jumps=3, max_flight_time=1000"""
    config = _configure(age=35, condition="neurological")
    assert config.min_contact_time == 100
    assert config.number_of_jumps == 3
    assert config.max_flight_time == 1000


# ── 无规则匹配 ──

def test_healthy_adult_defaults():
    """健康成年人 (age=30, healthy): 不触发任何规则，全默认值"""
    config = _configure(age=30, condition="healthy")
    assert config.min_contact_time == 60     # 默认值
    assert config.number_of_jumps == 5       # 默认值: 5次
    assert config.max_flight_time == 0       # 默认禁用
    assert config.stop_type == "Status change"


# ── 边界值 ──

def test_age_60_edge():
    """age=60 不触发老年人规则 (60 不 > 60)"""
    config = _configure(age=60, condition="healthy")
    assert config.min_contact_time == 60     # 默认值，未被规则修改
    assert config.number_of_jumps == 5


def test_age_61_edge():
    """age=61 触发老年人规则"""
    config = _configure(age=61, condition="healthy")
    assert config.min_contact_time == 80
    assert config.number_of_jumps == 3


def test_age_12_edge():
    """age=12 不触发儿童规则 (12 不 < 12)"""
    config = _configure(age=12, condition="healthy")
    assert config.min_contact_time == 60     # 默认值


def test_age_11_edge():
    """age=11 触发儿童规则"""
    config = _configure(age=11, condition="healthy")
    assert config.min_contact_time == 40


# ── 多规则叠加：保守聚合 ──

def test_elderly_post_surgery_overlap():
    """age=65 + post_surgery: min_contact = max(80, 100) = 100, jumps = min(3, 3) = 3"""
    config = _configure(age=65, condition="post_surgery")
    assert config.min_contact_time == 100    # 取最保守（最大值）
    assert config.number_of_jumps == 3


def test_elderly_neurological_overlap():
    """age=65 + neurological: min_contact=max(80, 100)=100, jumps=min(3, 3)=3, max_flight=1000"""
    config = _configure(age=65, condition="neurological")
    assert config.min_contact_time == 100
    assert config.number_of_jumps == 3
    assert config.max_flight_time == 1000


def test_max_flight_zero_skip():
    """max_flight_time: 0=禁用不参与聚合。只有 neurological 设了 1000，聚合 = 1000"""
    config = _configure(age=65, condition="neurological")
    # 老年人规则未设置 max_flight_time → 不加入聚合
    # 神经系统规则设置 1000 → 唯一非零值
    assert config.max_flight_time == 1000


# ── 顺序无关性 ──

def test_order_independence():
    """交换 PATIENT_RULES 顺序后，相同输入应得到相同输出"""
    import agent.rule_engine as re

    ctx = PatientContext(age=65, weight=70, height=170, condition="post_surgery")
    config_a = RuleEngine().configure("Jump Test", ctx)

    # 反转规则列表
    original = list(re.PATIENT_RULES)
    try:
        re.PATIENT_RULES[:] = original[::-1]
        config_b = RuleEngine().configure("Jump Test", ctx)
        assert config_a.min_contact_time == config_b.min_contact_time
        assert config_a.number_of_jumps == config_b.number_of_jumps
        assert config_a.max_flight_time == config_b.max_flight_time
    finally:
        re.PATIENT_RULES[:] = original


# ── 校验通过性 ──

def test_all_rules_produce_valid_config():
    """每条规则单独触发时，输出能通过 ParamSchema 校验"""
    from config.param_schema import get_schema

    schema = get_schema()
    test_cases = [
        ("老年", PatientContext(age=65, weight=70, height=170, condition="healthy")),
        ("儿童", PatientContext(age=10, weight=30, height=140, condition="healthy")),
        ("术后", PatientContext(age=35, weight=70, height=170, condition="post_surgery")),
        ("神经", PatientContext(age=35, weight=70, height=170, condition="neurological")),
        ("健康成人", PatientContext(age=30, weight=70, height=170, condition="healthy")),
        ("多规则", PatientContext(age=65, weight=70, height=170, condition="neurological")),
    ]
    for name, ctx in test_cases:
        config = RuleEngine().configure("Jump Test", ctx)
        values = config.to_dict()
        values.setdefault("test_macro_type", "Performance")
        errors = schema.validate(config.test_type, values)
        assert not errors, f"{name}: {errors}"
