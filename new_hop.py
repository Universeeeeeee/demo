"""
new_hop.py - 纵跳检测器 (仅使用前 48 个 LED)

基于 single_leg_hop_npz_parser.py 修改，仅检测前 48 个 LED 的状态，
忽略后 48 个 LED。

用于特定场景下只需要关注部分传感器区域的情况。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence


# ===================== 配置参数（修改为 48 个 LED）=====================

COLS = 48  # 只使用前 48 个 LED
SPACING_CM = 1.04


# ===================== 数据结构 =====================

@dataclass
class LedFrame:
    """原始 LED 帧"""
    timestamp: float
    bits: Sequence[int]  # 1 表示遮挡/触地


@dataclass
class Cluster:
    """连续遮挡段"""
    start: int
    end: int
    length: int
    centroid_idx: float
    centroid_cm: float
    ratio: float


@dataclass
class FootEvent:
    """步态事件"""
    kind: str  # "touch" 或 "lift"
    time: float
    ratio: float
    centroid_cm: Optional[float]


# ===================== 检测器（仅使用前 48 个 LED）=====================

class SingleFootDetector48:
    """
    单足触地/腾空检测状态机 - 48 LED 版本
    
    与原版 SingleFootDetector 的唯一区别：
    - 只处理前 48 个 LED 的状态
    - cols 默认为 48
    - 输入 bits 会被截取为前 48 位
    """

    def __init__(
        self,
        cols: int = COLS,
        spacing_cm: float = SPACING_CM,
        gap_threshold: int = 1,
        touch_ratio_threshold: float = 0.05,
        lift_ratio_threshold: float = 0.05,
        confirm_samples: int = 10,
    ) -> None:
        self.cols = cols
        self.spacing_cm = spacing_cm
        self.gap_threshold = gap_threshold
        self.touch_ratio_threshold = touch_ratio_threshold
        self.lift_ratio_threshold = lift_ratio_threshold
        self.confirm_samples = confirm_samples
        self._reset_state()

    def process(self, frames: Sequence[LedFrame]) -> List[FootEvent]:
        """批量处理多帧"""
        self.reset()
        events: List[FootEvent] = []
        for frame in frames:
            events.extend(self.consume(frame))
        return events

    def consume(self, frame: LedFrame) -> List[FootEvent]:
        """逐帧处理"""
        if self._prev_time is None:
            self._prev_time = frame.timestamp
        return self._process_frame(frame)

    def reset(self) -> None:
        self._reset_state()

    def _reset_state(self) -> None:
        self._state = "air"
        self._touch_streak = 0
        self._lift_streak = 0
        self._prev_ratio = 0.0
        self._prev_time: Optional[float] = None

    def _process_frame(self, frame: LedFrame) -> List[FootEvent]:
        # ===== 关键修改: 只取前 48 个 LED =====
        bits = frame.bits[:self.cols]
        
        cluster = self._extract_primary_cluster(bits)
        ratio = cluster.ratio if cluster else 0.0
        centroid = cluster.centroid_cm if cluster else None
        dt = max(frame.timestamp - (self._prev_time or frame.timestamp), 1e-3)
        self._prev_time = frame.timestamp
        self._prev_ratio = ratio
        events: List[FootEvent] = []

        touch_condition = (
            self._state == "air"
            and ratio >= self.touch_ratio_threshold
            and ratio < 0.38
        )
        lift_condition = (
            self._state == "ground"
            and (ratio <= self.lift_ratio_threshold or cluster is None)
        )

        if touch_condition:
            self._touch_streak += 1
            self._lift_streak = max(0, self._lift_streak - 1)
            if self._touch_streak >= self.confirm_samples:
                events.append(FootEvent("touch", frame.timestamp, ratio, centroid))
                self._state = "ground"
                self._touch_streak = 0
        elif lift_condition:
            self._lift_streak += 1
            self._touch_streak = max(0, self._touch_streak - 1)
            if self._lift_streak >= self.confirm_samples:
                events.append(FootEvent("lift", frame.timestamp, ratio, centroid))
                self._state = "air"
                self._lift_streak = 0
        else:
            self._touch_streak = max(0, self._touch_streak - 1)
            self._lift_streak = max(0, self._lift_streak - 1)
        return events

    def _extract_primary_cluster(self, bits: Sequence[int]) -> Optional[Cluster]:
        active = [idx for idx, val in enumerate(bits) if val]
        if not active:
            return None
        clusters = list(self._split_clusters(active))
        if not clusters:
            return None
        primary_cluster = max(clusters, key=lambda cl: cl.length)
        # 最小簇宽度：根据 48 LED 等比例调整为 5（原 96 LED 时为 10）
        if primary_cluster.length < 5:
            return None
        return primary_cluster

    def _split_clusters(self, active_indices: Sequence[int]) -> Iterable[Cluster]:
        if not active_indices:
            return []
        start = active_indices[0]
        prev = start
        for idx in active_indices[1:]:
            if idx - prev > self.gap_threshold:
                yield self._make_cluster(start, prev)
                start = idx
            prev = idx
        yield self._make_cluster(start, prev)

    def _make_cluster(self, start: int, end: int) -> Cluster:
        length = end - start + 1
        centroid_idx = (start + end) / 2.0
        centroid_cm = centroid_idx * self.spacing_cm
        ratio = length / self.cols  # 基于 48 个 LED 计算遮挡率
        return Cluster(start, end, length, centroid_idx, centroid_cm, ratio)


# 为了兼容性，也导出原名称的别名
SingleFootDetector = SingleFootDetector48


__all__ = [
    "LedFrame",
    "Cluster", 
    "FootEvent",
    "SingleFootDetector48",
    "SingleFootDetector",
    "COLS",
    "SPACING_CM",
]
