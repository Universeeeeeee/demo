"""基于 LED 压力阵列的步态分析工具集。

该模块实现完整的流水线：

1. 采样点去抖和平滑，保留稳定的 LED 状态
2. 聚合遮挡率与质心轨迹，构建全局特征
3. 检测触地/离地等关键事件
4. 输出触地时间、腾空时间、步幅等步态参数

调用方可通过 :class:`GaitAnalyzer` 提供的接口完成整套计算。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_CONFIG_FILENAME = "gait_config.json"


# ---------------------------------------------------------------------------
# 数据结构


@dataclass
class LedSample:
	"""单帧 LED 数据。

	参数
	----
	timestamp: float
		采样时间（秒）。
	bits: Sequence[int]
		LED 位图，0 表示亮灯/未遮挡，1 表示遮挡或受力，长度默认为 96。
	"""

	timestamp: float
	bits: Sequence[int]


@dataclass
class GaitEvent:
	"""步态事件（触地/离地）。"""

	kind: str
	time: float
	occlusion_ratio: float
	centroid: Optional[float]


@dataclass
class GaitCycle:
	"""单步/单跳周期的统计结果。"""

	touch_event: GaitEvent
	lift_event: Optional[GaitEvent]
	next_touch_event: Optional[GaitEvent]
	contact_duration: Optional[float]
	flight_duration: Optional[float]
	displacement_cm: Optional[float]
	stride_cm: Optional[float]


@dataclass
class GaitAnalysisResult:
	"""步态分析的整体输出。"""

	events: List[GaitEvent]
	cycles: List[GaitCycle]
	sampling_rate_hz: float


@dataclass
class GaitAnalyzerConfig:
	"""步态分析核心参数配置。"""

	rows: int = 1
	cols: int = 96
	spacing_cm: float = 1.04
	debounce_ms: float = 20.0
	smooth_window_ms: float = 50.0
	touch_ratio_threshold: float = 0.45
	lift_ratio_threshold: float = 0.15
	min_event_interval_ms: float = 120.0
	confirm_samples: int = 3
	min_contact_duration_ms: float = 160.0
	min_flight_duration_ms: float = 140.0
	min_cycle_interval_ms: float = 350.0

	def to_dict(self) -> Dict[str, Any]:
		return asdict(self)

	def override(self, **updates: Any) -> "GaitAnalyzerConfig":
		valid_keys = {f.name for f in fields(GaitAnalyzerConfig)}
		filtered = {k: v for k, v in updates.items() if k in valid_keys}
		return replace(self, **filtered)

	@classmethod
	def from_dict(cls, data: Dict[str, Any]) -> "GaitAnalyzerConfig":
		valid_keys = {f.name for f in fields(cls)}
		filtered = {k: data[k] for k in data if k in valid_keys}
		return cls(**filtered)

	@classmethod
	def from_json(cls, path: str) -> "GaitAnalyzerConfig":
		with open(path, "r", encoding="utf-8") as fp:
			payload = json.load(fp)
		return cls.from_dict(payload)


# ---------------------------------------------------------------------------
# 辅助函数


def _build_led_positions(rows: int, cols: int, spacing_cm: float) -> List[float]:
	positions: List[float] = []
	for r in range(rows):
		for c in range(cols):
			positions.append(c * spacing_cm)
	return positions


def _moving_average(values: Sequence[float], window: int) -> List[float]:
	if not values:
		return []
	if window < 20:
		window = 20
	if window > len(values):
		window = len(values)
	acc = 0.0
	out: List[float] = []
	buf: List[float] = []
	for v in values:
		buf.append(v)
		acc += v
		if len(buf) > window:
			acc -= buf.pop(0)
		out.append(acc / len(buf))
	return out

#计算导数，values为是被遮挡的led/96
def _diff(values: Sequence[float], dt: Sequence[float]) -> List[float]:
	deriv = [0.0]
	for i in range(1, len(values)):
		delta_t = max(dt[i], 1e-6)
		deriv.append((values[i] - values[i - 1]) / delta_t)
	return deriv


def _fill_missing_centroids(series: List[Optional[float]]) -> List[float]:
	last: Optional[float] = None
	for i, val in enumerate(series):
		if val is not None:
			last = val
		else:
			series[i] = last
	last = None
	for i in range(len(series) - 1, -1, -1):
		if series[i] is not None:
			last = series[i]
		else:
			series[i] = last
	filled: List[float] = []
	for val in series:
		filled.append(0.0 if val is None else val)
	return filled


# ---------------------------------------------------------------------------
# 主分析器


class GaitAnalyzer:
	"""把 LED 位图转换成步态事件与周期指标。

	- 优先从 `config_path` 指定的 JSON 读取参数；
	- 若未提供路径，则尝试加载与当前文件同目录的 ``gait_config.json``；
	- 如均不存在，则使用默认配置。
	可通过关键字参数覆盖任意配置字段，例如 ``GaitAnalyzer(confirm_samples=3)``。
	"""

	def __init__(
		self,
		config: Optional[GaitAnalyzerConfig] = None,
		config_path: Optional[str] = None,
		**overrides: Any,
	):
		self.config = self._resolve_config(config, config_path, overrides)
		self.rows = self.config.rows
		self.cols = self.config.cols
		self.total_leds = self.config.rows * self.config.cols
		self.spacing_cm = self.config.spacing_cm
		self.debounce_ms = self.config.debounce_ms
		self.smooth_window_ms = self.config.smooth_window_ms
		self.touch_ratio_threshold = self.config.touch_ratio_threshold
		self.lift_ratio_threshold = self.config.lift_ratio_threshold
		self.min_event_interval_ms = self.config.min_event_interval_ms
		self.confirm_samples = max(1, int(self.config.confirm_samples))
		self.min_contact_duration_ms = self.config.min_contact_duration_ms
		self.min_flight_duration_ms = self.config.min_flight_duration_ms
		self.min_cycle_interval_ms = self.config.min_cycle_interval_ms
		self.positions_x = _build_led_positions(self.rows, self.cols, self.spacing_cm)

	def _resolve_config(
		self,
		config: Optional[GaitAnalyzerConfig],
		config_path: Optional[str],
		overrides: Dict[str, Any],
	) -> GaitAnalyzerConfig:
		if config is None:
			actual_path: Optional[Path] = None
			if config_path:
				candidate = Path(config_path)
				if not candidate.exists():
					raise FileNotFoundError(f"找不到配置文件: {config_path}")
				actual_path = candidate
			else:
				default_path = Path(__file__).with_name(DEFAULT_CONFIG_FILENAME)
				if default_path.exists():
					actual_path = default_path
			config = (
				GaitAnalyzerConfig.from_json(str(actual_path))
				if actual_path
				else GaitAnalyzerConfig()
			)
		if overrides:
			config = config.override(**overrides)
		return config

	# ---------------------------- 公共 API ----------------------------

	def compute_stride(self, e1: GaitEvent, e2: GaitEvent) -> Optional[float]:
		"""计算并验证两个事件之间的步幅（单位：cm）。
		
		这是一个公共方法，供外部调用以计算步幅，会自动进行异常值过滤。
		
		参数
		----
		e1: GaitEvent
			第一个触地事件。
		e2: GaitEvent
			第二个触地事件。
		
		返回
		----
		Optional[float]
			验证通过的步幅值（单位：cm），若计算失败或超出合理范围则返回 None。
		"""
		stride = self._distance_between_events(e1, e2)
		return self._validate_stride(stride)

	def process(self, samples: Sequence[LedSample]) -> GaitAnalysisResult:
		if len(samples) < 2:
			raise ValueError("至少需要两帧 LED 数据才能计算步态参数")

		timestamps = [sample.timestamp for sample in samples]
		dt = self._compute_dt_series(timestamps)
		sampling_rate = 1.0 / max(sum(dt) / len(dt), 1e-6)

		occlusion_ratio, centroid_series = self._aggregate_metrics(samples)
		occlusion_ratio = self._smooth_series(occlusion_ratio, sampling_rate)
		centroid_series = self._smooth_centroids(centroid_series, sampling_rate)
		centroid_speed = self._compute_centroid_speed(centroid_series, dt)
		ratio_derivative = _diff(occlusion_ratio, dt)

		events = self._detect_events(
			timestamps,
			occlusion_ratio,
			ratio_derivative,
			centroid_series,
			centroid_speed,
		)
		cycles = self._build_cycles(events)
		return GaitAnalysisResult(events=events, cycles=cycles, sampling_rate_hz=sampling_rate)

	# --------------------------- 预处理阶段 --------------------------

	def _compute_dt_series(self, timestamps: Sequence[float]) -> List[float]:
		dt = [max(timestamps[i] - timestamps[i - 1], 1e-6) for i in range(1, len(timestamps))]
		dt.insert(0, dt[0])
		return dt

	def _aggregate_metrics(self, samples: Sequence[LedSample]) -> Tuple[List[float], List[Optional[float]]]:
		ratios: List[float] = []
		centroids: List[Optional[float]] = []
		for sample in samples:
			active_indices = [idx for idx, state in enumerate(sample.bits) if state]
			ratio = len(active_indices) / self.total_leds
			ratios.append(ratio)
			if active_indices:
				xs = [self.positions_x[idx] for idx in active_indices]
				centroids.append(sum(xs) / len(xs))
			else:
				centroids.append(None)
		return ratios, centroids

	def _smooth_series(self, series: Sequence[float], sampling_rate: float) -> List[float]:
		window = max(int(self.smooth_window_ms * sampling_rate / 1000.0), 1)
		return _moving_average(series, window)

	def _smooth_centroids(self, centroids: List[Optional[float]], sampling_rate: float) -> List[float]:
		filled = _fill_missing_centroids(centroids)
		window = max(int(self.smooth_window_ms * sampling_rate / 1000.0), 1)
		return _moving_average(filled, window)

	def _compute_centroid_speed(self, centroids: Sequence[float], dt: Sequence[float]) -> List[float]:
		diffs: List[float] = [0.0]
		for i in range(1, len(centroids)):
				dx = centroids[i] - centroids[i - 1]
				diffs.append(dx)
		speeds = []
		for delta, delta_t in zip(diffs, dt):
			speeds.append(abs(delta) / max(delta_t, 1e-6))
		avg_dt = sum(dt) / len(dt)
		window = max(int(self.debounce_ms / 1000.0 / max(avg_dt, 1e-6)), 1)
		return _moving_average(speeds, window)

	# ---------------------------- 事件逻辑 ---------------------------

	def _detect_events(
		self,
		timestamps: Sequence[float],
		ratios: Sequence[float],
		ratio_derivative: Sequence[float],
		centroids: Sequence[float],
		centroid_speed: Sequence[float],
	) -> List[GaitEvent]:
		events: List[GaitEvent] = []
		state = "air"
		min_interval = self.min_event_interval_ms / 1000.0
		min_contact = self.min_contact_duration_ms / 1000.0
		min_flight = self.min_flight_duration_ms / 1000.0
		min_cycle = self.min_cycle_interval_ms / 1000.0
		last_event_time = -1e9
		last_touch_time: Optional[float] = None
		last_lift_time: Optional[float] = None
		touch_candidate = 0
		lift_candidate = 0
		confirm_needed = self.confirm_samples
		for t, ratio, d_ratio, centroid, speed in zip(timestamps, ratios, ratio_derivative, centroids, centroid_speed):
			if t - last_event_time < min_interval:
				continue
			grad_trigger = abs(self.touch_ratio_threshold) * 0.2
			touch_condition = state == "air" and ratio >= self.touch_ratio_threshold and d_ratio > grad_trigger
			lift_condition = state == "ground" and ratio <= self.lift_ratio_threshold and d_ratio < -grad_trigger
			if touch_condition:
				touch_candidate += 1
				lift_candidate = max(0, lift_candidate - 1)
				if touch_candidate >= confirm_needed:
					if last_touch_time is not None and t - last_touch_time < min_cycle:
						touch_candidate = 0
						continue
					if last_lift_time is not None and t - last_lift_time < min_flight:
						touch_candidate = 0
						continue
					events.append(GaitEvent("touch", t, ratio, centroid))
					state = "ground"
					last_event_time = t
					last_touch_time = t
					touch_candidate = 0
			elif lift_condition:
				lift_candidate += 1
				touch_candidate = max(0, touch_candidate - 1)
				if lift_candidate >= confirm_needed:
					if last_touch_time is None or t - last_touch_time < min_contact:
						lift_candidate = 0
						continue
					events.append(GaitEvent("lift", t, ratio, centroid))
					state = "air"
					last_event_time = t
					last_lift_time = t
					lift_candidate = 0
			else:
				touch_candidate = max(0, touch_candidate - 1)
				lift_candidate = max(0, lift_candidate - 1)
		return events

	# --------------------------- 周期计算 ---------------------------

	def _build_cycles(self, events: Sequence[GaitEvent]) -> List[GaitCycle]:
		cycles: List[GaitCycle] = []
		min_contact = self.min_contact_duration_ms / 1000.0
		min_flight = self.min_flight_duration_ms / 1000.0
		min_cycle = self.min_cycle_interval_ms / 1000.0
		last_appended_touch: Optional[float] = None
		for idx, touch in enumerate(events):
			if touch.kind != "touch":
				continue
			if last_appended_touch is not None and touch.time - last_appended_touch < min_cycle:
				continue
			lift = next((ev for ev in events[idx + 1 :] if ev.kind == "lift"), None)
			next_touch = next((ev for ev in events[idx + 1 :] if ev.kind == "touch"), None)
			contact_duration = None
			flight_duration = None
			displacement = None
			stride = None
			if lift is not None:
				contact_duration = max(lift.time - touch.time, 0.0)
				displacement = self._distance_between_events(touch, lift)
				if next_touch is not None:
					flight_duration = max(next_touch.time - lift.time, 0.0)
			if contact_duration is not None and contact_duration < min_contact:
				continue
			if next_touch is not None:
				stride = self._distance_between_events(touch, next_touch)
				stride = self._validate_stride(stride)  # 验证并过滤异常值
				if flight_duration is not None and flight_duration < min_flight:
					flight_duration = None
			cycles.append(
				GaitCycle(
					touch_event=touch,
					lift_event=lift,
					next_touch_event=next_touch,
					contact_duration=contact_duration,
					flight_duration=flight_duration,
					displacement_cm=displacement,
					stride_cm=stride,
				)
			)
			last_appended_touch = touch.time
		return cycles

	# ----------------------------- 其他 -----------------------------

	def _distance_between_events(self, e1: GaitEvent, e2: GaitEvent) -> Optional[float]:
		"""计算两个事件之间的水平距离（单位：cm）。"""
		if e1.centroid is None or e2.centroid is None:
			return None
		dx = e2.centroid - e1.centroid
		return abs(dx)

	def _validate_stride(self, stride: Optional[float]) -> Optional[float]:
		"""验证步幅的合理性，过滤异常值。
		
		参数
		----
		stride: Optional[float]
			待验证的步幅值（单位：cm）。
		
		返回
		----
		Optional[float]
			验证通过的步幅值，若超出合理范围则返回 None。
		"""
		if stride is None:
			return None
		# 计算理论最大步幅：基于 LED 阵列尺寸
		# 考虑对角线距离作为最大可能值，并允许一定的容差（1.5倍）
		max_theoretical = ((self.cols * self.spacing_cm) ** 2 + 
		                  (self.rows * self.spacing_cm) ** 2) ** 0.5
		max_stride = max_theoretical * 1.5  # 允许1.5倍最大理论值
		# 最小步幅：基于LED阵列尺寸，最小应该跨越至少2个LED间距
		# 但考虑到实际步态，正常步幅应该在 30-150cm 左右
		# 如果步幅小于2个LED间距，可能是噪声或重复检测
		min_stride = self.spacing_cm * 2.0  # 最小为2倍间距（约2.08cm）
		# 对于步行模式，实际步幅应该更大，但这里只做基本过滤
		# 如果步幅在合理范围内，返回；否则可能是噪声
		if min_stride <= stride <= max_stride:
			return stride
		# 如果步幅小于最小值，可能是噪声或重复检测，返回None
		# 如果步幅大于最大值，可能是计算错误，也返回None
		return None  # 超出合理范围，标记为无效


__all__ = [
	"LedSample",
	"GaitEvent",
	"GaitCycle",
	"GaitAnalysisResult",
	"GaitAnalyzerConfig",
	"GaitAnalyzer",
]

