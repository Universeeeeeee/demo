# rule_engine.py — 规则引擎（离线模式）
# 根据用户信息自动推荐 OptoJump 测试参数，无需网络连接
#
# 数据流:
#   test_type (str) + AthleteProfile → TestConfig
#   输出与 ParamPanel.get_config() 完全一致，可直接传入 GaitEngine

from __future__ import annotations

from typing import Callable

from config.test_config import TestConfig, default_jump_config
from config.param_schema import get_schema
from .models import AthleteProfile


# ---- 参数修正规则 ----
#
# 格式: (条件函数, 要覆盖的 TestConfig 字段字典)
#
# 规则按列表顺序逐条应用，后面的规则覆盖前面的。
#
# 扩展方式:
#   1. 添加新规则 — 在列表末尾追加 (条件函数, 覆盖字典) 元组
#   2. 可覆盖的字段 — TestConfig 的任意字段:
#      stop_type, number_of_jumps, test_length,
#      min_contact_time, min_flight_time, max_flight_time, ...
#   3. 条件函数签名: (AthleteProfile) -> bool
#
ProfileRule = tuple[Callable[[AthleteProfile], bool], dict]

PROFILE_RULES: list[ProfileRule] = [
    # 年长用户 (>60): 触地时间更长，减少跳跃次数
    (lambda ctx: ctx.age > 60,
     {"min_contact_time": 80, "number_of_jumps": 3}),

    # 儿童 (<12): 触地时间更短
    (lambda ctx: ctx.age < 12,
     {"min_contact_time": 40, "number_of_jumps": 3}),

    # 入门用户: 保守参数
    (lambda ctx: ctx.level == "beginner",
     {"min_contact_time": 100, "number_of_jumps": 3}),
]


class RuleEngine:
    """
    规则引擎 — 根据用户信息自动调整测试参数

    职责:
      - 以 default_jump_config() 为基准
      - 按用户条件逐条修正 TestConfig 字段
      - 用 ParamSchema.validate() 校验输出合法性

    不做:
      - 不识别意图（test_type 由 UI 直接传入）
      - 不涉及 LLM（纯规则映射）
    """

    def __init__(self):
        self._schema = get_schema()

    def configure(self, test_type: str, ctx: AthleteProfile) -> TestConfig:
        """
        生成测试配置。

        Args:
            test_type: 测试类型字符串，如 "Jump Test"
            ctx: 用户运动档案

        Returns:
            TestConfig — 与 ParamPanel.get_config() 输出格式一致

        Raises:
            ValueError: 如果生成的配置未通过 schema 校验
        """
        # 1. 基准配置
        config = default_jump_config()
        config.test_type = test_type

        # 2. 按用户条件修正
        self._apply_rules(config, ctx)

        # 3. schema 校验
        self._validate(config)

        return config

    # 保守聚合：多条规则命中同一字段时取最保守值，不依赖规则顺序
    _MERGE_MAX = {"min_contact_time", "min_flight_time"}       # 越大越保守
    _MERGE_MIN = {"number_of_jumps"}                           # 越小越保守
    _MERGE_MIN_NONZERO = {"max_flight_time"}                   # 0=禁用，非零值越小越保守

    def _apply_rules(self, config: TestConfig, ctx: AthleteProfile) -> None:
        """收集匹配规则的覆盖值，保守聚合后应用到 config。"""
        collected: dict[str, list] = {}
        for condition_fn, overrides in PROFILE_RULES:
            if condition_fn(ctx):
                for field_name, value in overrides.items():
                    collected.setdefault(field_name, []).append(value)

        # 聚合
        merged = {}
        for field_name, values in collected.items():
            if field_name in self._MERGE_MAX:
                merged[field_name] = max(values)
            elif field_name in self._MERGE_MIN:
                merged[field_name] = min(values)
            elif field_name in self._MERGE_MIN_NONZERO:
                nonzero = [v for v in values if v != 0]
                merged[field_name] = min(nonzero) if nonzero else 0
            else:
                # 未明确定义聚合策略的字段：取最后一个匹配规则的值（兼容扩展）
                merged[field_name] = values[-1]

        for field_name, value in merged.items():
            setattr(config, field_name, value)

    def _validate(self, config: TestConfig) -> None:
        """用 ParamSchema 校验配置合法性。"""
        values = config.to_dict()
        # test_macro_type 是 UI 选择层参数，TestConfig 不包含，手动补充
        values.setdefault("test_macro_type", "Performance")
        errors = self._schema.validate(config.test_type, values)
        if errors:
            raise ValueError(f"规则引擎生成的配置不合法: {errors}")

