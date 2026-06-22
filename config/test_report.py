"""
test_report.py — 不可变测试结果快照

由 SessionController 在测试结束时从 GaitEngine 提取数据构造。
ReportView 只依赖此 dataclass，不依赖 GaitEngine。
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional, Union

G = 9.81  # 重力加速度


def _positive_values(values) -> tuple[float, ...]:
    return tuple(float(value) for value in values if value > 0)


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values) if values else 0.0


def _min_or_zero(values: tuple[float, ...]) -> float:
    return min(values) if values else 0.0


def _max_or_zero(values: tuple[float, ...]) -> float:
    return max(values) if values else 0.0


def _population_std(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    avg = _mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def _jump_heights(air_times: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(0.5 * G * (air_time / 2) ** 2 for air_time in air_times)


def _cadences(cycle_times: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(60.0 / cycle_time for cycle_time in cycle_times)


@dataclass(frozen=True)
class JumpTestReport:
    """纵跳测试结果快照（不可变）"""
    touch_count: int
    lift_count: int
    air_times: tuple[float, ...]
    contact_times: tuple[float, ...]
    cycle_times: tuple[float, ...]
    # 派生指标
    avg_jump_height: float
    max_jump_height: float
    avg_air_time: float
    max_air_time: float
    avg_contact_time: float
    avg_cadence: Optional[float]   # 60/avg_cycle, 无数据时 None
    finish_reason: str             # "jump_count_reached" | "time_up" | "manual"
    jump_heights: tuple[float, ...] = ()
    cadences: tuple[float, ...] = ()
    min_jump_height: float = 0.0
    std_jump_height: float = 0.0
    min_air_time: float = 0.0
    std_air_time: float = 0.0
    min_contact_time: float = 0.0
    max_contact_time: float = 0.0
    std_contact_time: float = 0.0
    # 原始导出帧 (可选，用于 Excel 导出)
    export_frames: tuple = ()
    export_timestamps: tuple = ()


@dataclass(frozen=True)
class GaitTestReport:
    """步态测试结果快照（不可变）"""
    touch_count: int
    lift_count: int
    stride_lengths: tuple
    velocities: tuple
    avg_stride: float
    max_stride: float
    avg_velocity: float
    max_velocity: float
    # 支撑时间
    foot_a_support_times: tuple = ()
    foot_b_support_times: tuple = ()
    # 高阶指标
    imbalance_index: Optional[float] = None
    avg_double_support: Optional[float] = None
    avg_single_support: Optional[float] = None
    avg_acceleration: Optional[float] = None
    finish_reason: str = "manual"
    # 原始导出帧
    export_frames: tuple = ()
    export_timestamps: tuple = ()


# 统一类型别名
TestReport = Union[JumpTestReport, GaitTestReport]


def build_report(engine, reason: str = "manual") -> TestReport:
    """从 GaitEngine 实例提取数据，构造不可变报告。

    必须在线程停止后、engine 引用释放前调用。
    """
    mode = engine.mode

    # 提取导出帧 (转为 tuple 确保不可变)
    export_frames = tuple(list(f) for f in engine.export_frames)
    export_timestamps = tuple(engine.export_timestamps)

    if mode == "纵跳":
        air = _positive_values(engine.air_times)
        contact = _positive_values(engine.contact_times)
        cycle = _positive_values(engine.cycle_times)

        heights = _jump_heights(air)
        cadence_values = _cadences(cycle)
        avg_air = _mean(air)
        avg_contact = _mean(contact)
        avg_cycle = _mean(cycle)

        return JumpTestReport(
            touch_count=engine.touch_count,
            lift_count=engine.lift_count,
            air_times=air,
            contact_times=contact,
            cycle_times=cycle,
            avg_jump_height=_mean(heights),
            max_jump_height=_max_or_zero(heights),
            avg_air_time=avg_air,
            max_air_time=_max_or_zero(air),
            avg_contact_time=avg_contact,
            avg_cadence=60.0 / avg_cycle if avg_cycle > 0 else None,
            finish_reason=reason,
            jump_heights=heights,
            cadences=cadence_values,
            min_jump_height=_min_or_zero(heights),
            std_jump_height=_population_std(heights),
            min_air_time=_min_or_zero(air),
            std_air_time=_population_std(air),
            min_contact_time=_min_or_zero(contact),
            max_contact_time=_max_or_zero(contact),
            std_contact_time=_population_std(contact),
            export_frames=export_frames,
            export_timestamps=export_timestamps,
        )
    else:
        # 步态模式
        ct = engine.contact_tracker
        strides = tuple(ct.stride_lengths) if ct and ct.stride_lengths else ()
        vels = tuple(ct.velocities) if ct and ct.velocities else ()
        fa = tuple(ct.foot_a_support_times) if ct and ct.foot_a_support_times else ()
        fb = tuple(ct.foot_b_support_times) if ct and ct.foot_b_support_times else ()

        avg_stride = sum(strides) / len(strides) if strides else 0.0
        max_stride = max(strides) if strides else 0.0
        avg_vel = sum(vels) / len(vels) if vels else 0.0
        max_vel = max(vels) if vels else 0.0

        # 高阶指标: 从 extra_metrics_history 聚合
        imbalance = None
        avg_ds = None
        avg_ss = None
        avg_acc = None
        if ct and ct.extra_metrics_history:
            _extract = lambda key: [m[key] for m in ct.extra_metrics_history if m.get(key) is not None]
            ii_vals = _extract("imbalance_index")
            ds_vals = _extract("double_support")
            ss_vals = _extract("single_support")
            acc_vals = _extract("acceleration")
            imbalance = sum(ii_vals) / len(ii_vals) if ii_vals else None
            avg_ds = sum(ds_vals) / len(ds_vals) if ds_vals else None
            avg_ss = sum(ss_vals) / len(ss_vals) if ss_vals else None
            avg_acc = sum(acc_vals) / len(acc_vals) if acc_vals else None

        return GaitTestReport(
            touch_count=engine.touch_count,
            lift_count=engine.lift_count,
            stride_lengths=strides,
            velocities=vels,
            avg_stride=avg_stride,
            max_stride=max_stride,
            avg_velocity=avg_vel,
            max_velocity=max_vel,
            foot_a_support_times=fa,
            foot_b_support_times=fb,
            imbalance_index=imbalance,
            avg_double_support=avg_ds,
            avg_single_support=avg_ss,
            avg_acceleration=avg_acc,
            finish_reason=reason,
            export_frames=export_frames,
            export_timestamps=export_timestamps,
        )
