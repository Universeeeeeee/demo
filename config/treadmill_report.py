"""
treadmill_report.py — 跑步机测试结果报告数据模型

定义了逐步结果、MetricSummary、报告基类和具体报告类型。
MetricSummary 对空序列返回 None 指标，不返回 0.0，
避免把"没有数据"和"真实为 0"混淆。

单位后缀约定：
  _s          秒
  _cm         厘米
  _m_s        米/秒
  _steps_per_s  步/秒
  _percent    百分比
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Literal

from config.treadmill_config import FootSide, StartingFootSource


# ---- 汇总统计 ----

@dataclass(frozen=True)
class MetricSummary:
    """对一组结果参数的统计摘要。

    mean/min/max/std/cv_percent 对空序列返回 None，
    避免把"没有数据"和"真实为 0"混淆。
    """
    count: int
    mean: float | None
    min: float | None
    max: float | None
    std: float | None
    cv_percent: float | None


def summarize(values: tuple[float, ...]) -> MetricSummary:
    """对一组数值计算统计摘要，使用总体标准差。"""
    if not values:
        return MetricSummary(0, None, None, None, None, None)
    mean = sum(values) / len(values)
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    cv = std / mean * 100 if mean else None
    return MetricSummary(
        count=len(values),
        mean=mean,
        min=min(values),
        max=max(values),
        std=std,
        cv_percent=cv,
    )


# ---- 行状态和修正来源类型 ----

RowStatus = Literal[
    "valid",
    "deleted",
    "tc_not_valid",
    "tf_not_valid",
    "no_step",
    "suspended",
    "split",
    "external",
]

CorrectionSource = Literal[
    "none",
    "threshold_filter",
    "automatic_data_filter",
    "manual_delete_row",
    "manual_delete_contact",
    "manual_delete_flight",
    "manual_restore",
]


# ---- 逐步结果 ----

@dataclass(frozen=True)
class TreadmillStepResult:
    """跑步机测试的单个步态周期结果行。"""
    index: int
    side: FootSide
    row_status: RowStatus
    is_event_valid: bool
    is_included_in_statistics: bool
    correction_source: CorrectionSource
    event_invalid_reason: str | None = None
    statistics_exclusion_reason: str | None = None
    time_s: float | None = None
    distance_cm: float | None = None
    contact_time_s: float | None = None
    flight_time_s: float | None = None
    step_time_s: float | None = None
    gait_cycle_s: float | None = None
    step_length_cm: float | None = None
    stride_length_cm: float | None = None
    speed_m_s: float | None = None
    cadence_steps_per_s: float | None = None
    double_support_s: float | None = None
    single_support_s: float | None = None
    stance_phase_s: float | None = None
    swing_phase_s: float | None = None
    load_response_s: float | None = None
    pre_swing_s: float | None = None
    contact_phase_s: float | None = None
    foot_flat_s: float | None = None
    propulsive_phase_s: float | None = None
    imbalance_percent: float | None = None


# ---- 报告基类 ----

@dataclass(frozen=True)
class TreadmillReportBase:
    """跑步机测试报告基类，包含所有公共字段。"""
    finish_reason: str
    touch_count: int
    lift_count: int
    resolved_starting_foot: FootSide
    starting_foot_source: StartingFootSource
    foot_length_cm_snapshot: float | None = None
    foot_length_source: str = "unknown"
    per_step_results: tuple[TreadmillStepResult, ...] = ()
    metric_summaries: dict[str, MetricSummary] = field(default_factory=dict)
    left_right_results: dict[str, MetricSummary] = field(default_factory=dict)
    asymmetry_metrics: dict[str, float] = field(default_factory=dict)
    report_config_snapshot: dict[str, Any] = field(default_factory=dict)
    export_frames: tuple = ()
    export_timestamps: tuple = ()


# ---- 具体报告类型 ----

@dataclass(frozen=True)
class TreadmillGaitReport(TreadmillReportBase):
    """跑步机步态测试结果报告。"""

    @property
    def test_type(self) -> str:
        return "Treadmill Gait Test"


@dataclass(frozen=True)
class TreadmillRunningReport(TreadmillReportBase):
    """跑步机跑步测试结果报告。"""

    @property
    def test_type(self) -> str:
        return "Treadmill Running Test"
