"""
gait_engine.py — 独立算法引擎（L2 算法层）

职责:
  - 接收 UsbWorker 的 raw_contact_signal（96 位无损接触状态 + 精确时间戳）
  - 在后台线程内执行簇提取、轨迹追踪、触地/离地状态机
  - 发射高级事件信号（hop_event / gait_step_event）给 UI 层
  - 内部缓存导出数据，供结束时一次性读取

设计约束:
  - 不 import 任何 QtWidgets，只依赖 QObject / Signal / Slot
  - 与 UsbWorker 共享同一个 QThread，通过 DirectConnection 连接
  - 所有公共属性均为只读统计数据，供 UI 在结束时读取汇总
"""
from __future__ import annotations

import logging

import time
import traceback
from collections import deque
from typing import List, Optional

from qtpy.QtCore import QObject, Signal, Slot, QTimer

# 配置容器
try:
    from config.test_config import TestConfig
except ImportError:
    from ..config.test_config import TestConfig

log = logging.getLogger(__name__)

# 纵跳检测器
try:
    from .single_foot_tracker import SingleFootDetector, LedFrame, FootEvent
except ImportError:
    from single_foot_tracker import SingleFootDetector, LedFrame, FootEvent

# 步态聚类与追踪
try:
    from .spatial_clusterer import ClusterTracker, extract_clusters
except ImportError:
    from spatial_clusterer import ClusterTracker, extract_clusters

# Contact-Based 步态事件检测器
try:
    from .contact_tracker import ContactBasedGaitTracker, GaitStepEvent
except ImportError:
    from contact_tracker import ContactBasedGaitTracker, GaitStepEvent


G = 9.81  # 重力加速度
MAX_EXPORT_FRAMES = 600_000  # 导出缓存上限 (10 分钟 @1000Hz, ~230MB)


class GaitEngine(QObject):
    """
    算法引擎 — 纯计算，无 UI 依赖。

    信号流:
        UsbWorker.raw_contact_signal  →  process_raw_frame()  →  hop_event / gait_step_event  →  UI

    使用方式::

        engine = GaitEngine(mode="纵跳")
        engine.moveToThread(worker_thread)
        usb_worker.raw_contact_signal.connect(engine.process_raw_frame, Qt.DirectConnection)
        engine.hop_event.connect(ui._on_hop_event)          # QueuedConnection 跨线程
        engine.gait_step_event.connect(ui._on_gait_step_event)
    """

    # === 高级事件信号 (跨线程发往 UI，低频: 每秒 2~5 次) ===
    hop_event = Signal(object)            # FootEvent, 纵跳模式的触地/腾空
    gait_step_event = Signal(object)      # GaitStepEvent, 步态模式的触地/离地

    # === 步态模式周期性状态快照 (节流: ~10Hz，供 UI 面板刷新) ===
    gait_status_snapshot = Signal(dict)   # 当前状态快照 dict

    # === 自动停止信号 ===
    test_finished = Signal(str)           # 结束原因: "jump_count_reached" | "time_up"

    def __init__(self, config: TestConfig | None = None, *, mode: str = "纵跳", parent=None):
        """
        初始化算法引擎。

        推荐用法 (P3+)::

            config = TestConfig(test_type="Jump Test", ...)
            engine = GaitEngine(config=config)

        向后兼容 (旧用法)::

            engine = GaitEngine(mode="纵跳")  # 使用默认 TestConfig
        """
        super().__init__(parent)

        # 构建配置: 优先使用传入的 config，否则按 mode 字符串构造默认配置
        if config is not None:
            self._config = config
        else:
            from config.test_config import default_jump_config
            self._config = default_jump_config()
            if mode != "纵跳":
                self._config.test_type = "Sprint and Gait Test"

        self._mode = "纵跳" if self._config.test_type == "Jump Test" else "步态分析"
        self._start_time: Optional[float] = None
        self._paused = False
        self._finished = False  # 防止重复发射 test_finished

        # ---- 纵跳模式内部状态 ----
        self._detector: Optional[SingleFootDetector] = None

        # 纵跳统计 (镜像原 data_show 的字段，供 UI 结束时读取)
        self.touch_count = 0
        self.lift_count = 0
        self.last_touch_time: Optional[float] = None
        self.last_lift_time: Optional[float] = None
        self.cycle_times: List[float] = []
        self.air_times: List[float] = []
        self.contact_times: List[float] = []

        # ---- 步态模式内部状态 ----
        self._cluster_tracker: Optional[ClusterTracker] = None
        self._contact_tracker: Optional[ContactBasedGaitTracker] = None

        # ---- 导出缓存 (FIFO 有限队列，防止长期运行 OOM) ----
        self._export_frames: deque = deque(maxlen=MAX_EXPORT_FRAMES)
        self._export_timestamps: deque = deque(maxlen=MAX_EXPORT_FRAMES)

        # ---- 步态状态快照节流 ----
        self._last_snapshot_ts = 0.0
        self._snapshot_interval = 0.1  # 100ms = ~10Hz

        # ---- End of Time 倒计时 ----
        self._stop_timer: Optional[QTimer] = None

        # 初始化检测器
        self._init_detectors()

    # ---------------------------------------------------------------
    #  配置
    # ---------------------------------------------------------------

    def set_start_time(self, t: float):
        """设置时间基准（由 UI 在点击'开始分析'时调用），并启动倒计时。"""
        self._start_time = t
        self._start_timer()

    def set_mode(self, mode: str):
        """切换模式并重置内部状态"""
        self._mode = mode
        self.reset()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def config(self) -> TestConfig:
        return self._config

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, val: bool):
        self._paused = val
        # 暂停时重置检测器的连续帧计数器，避免恢复后读到过时的 streak
        if val and self._detector is not None:
            self._detector._touch_streak = 0
            self._detector._lift_streak = 0

    def _init_detectors(self):
        """根据当前模式初始化对应的检测器实例，滤波参数从 TestConfig 读取"""
        if self._mode == "纵跳":
            self._detector = SingleFootDetector(
                touch_ratio_threshold=0.12,
                lift_ratio_threshold=0.05,
                confirm_samples=2,
            )
            self._cluster_tracker = None
            self._contact_tracker = None
        else:
            self._cluster_tracker = ClusterTracker()
            self._contact_tracker = ContactBasedGaitTracker()
            self._detector = None

    def reset(self):
        """重置所有算法和统计状态"""
        # 纵跳统计
        self.touch_count = 0
        self.lift_count = 0
        self.last_touch_time = None
        self.last_lift_time = None
        self.cycle_times = []
        self.air_times = []
        self.contact_times = []
        self._finished = False

        # 步态追踪器
        if self._contact_tracker is not None:
            self._contact_tracker.reset()

        # 导出缓存
        self._export_frames.clear()
        self._export_timestamps.clear()

        # 快照节流
        self._last_snapshot_ts = 0.0

        # 停止计时器
        if self._stop_timer is not None:
            self._stop_timer.stop()
            self._stop_timer = None

        # 重新初始化检测器
        self._init_detectors()

    # ---------------------------------------------------------------
    #  导出数据访问 (供 UI 结束时读取)
    # ---------------------------------------------------------------

    @property
    def export_frames(self) -> List[List[int]]:
        return self._export_frames

    @property
    def export_timestamps(self) -> List[float]:
        return self._export_timestamps

    @property
    def contact_tracker(self) -> Optional[ContactBasedGaitTracker]:
        """暴露 ContactBasedGaitTracker 实例，供 UI 结束时读取汇总统计"""
        return self._contact_tracker

    # ---------------------------------------------------------------
    #  核心入口 (由 UsbWorker.raw_contact_signal → DirectConnection 调用)
    # ---------------------------------------------------------------

    @Slot(list, float)
    def process_raw_frame(self, contact_bits: list, timestamp: float):
        """
        处理单帧原始接触数据。

        在后台线程内被 DirectConnection 同步调用，
        每秒可能执行数百到一千次。

        参数:
            contact_bits: 96 位接触状态列表 (1=触地)
            timestamp: time.perf_counter() 绝对时间
        """
        if self._paused:
            return

        # 转换为相对时间
        rel_time = timestamp - self._start_time if self._start_time else 0.0

        # 记录到导出缓存
        self._export_frames.append(list(contact_bits))
        self._export_timestamps.append(rel_time)

        # 分发到对应模式的处理器
        if self._mode == "纵跳":
            self._process_hop(contact_bits, rel_time)
        else:
            self._process_gait(contact_bits, rel_time, timestamp)

    # ---------------------------------------------------------------
    #  纵跳模式处理
    # ---------------------------------------------------------------

    def _process_hop(self, bits: list, rel_time: float):
        """纵跳模式：使用 SingleFootDetector 逐帧检测"""
        frame = LedFrame(timestamp=rel_time, bits=bits)
        for ev in self._detector.consume(frame):
            self._accumulate_hop_stats(ev)
            self.hop_event.emit(ev)  # → UI (低频)

    def _accumulate_hop_stats(self, ev: FootEvent):
        """累积纵跳统计数据，并将计算值附加到事件对象（避免跨线程取值竞态）。

        滤波规则 (来自 OptoJump 说明书 4.2.2.2):
          - min_contact_time: 低于此值的接触时间合并到关联腾空时间
          - min_flight_time:  低于此值的腾空时间合并到关联接触时间
          - max_flight_time:  超过此值的腾空时间直接丢弃
        """
        ev._air_time = None
        ev._contact_time = None
        ev._hop_height = None

        cfg = self._config

        if ev.kind.lower() == "touch":
            self.touch_count += 1
            if self.last_lift_time is not None:
                air_time = ev.time - self.last_lift_time
                if air_time > 0:
                    # 滤波: max_flight_time — 超过上限的腾空直接丢弃
                    if cfg.max_flight_time > 0 and air_time * 1000 > cfg.max_flight_time:
                        log.debug("air_time %.1fms > max_flight_time %dms, discarded",
                                  air_time * 1000, cfg.max_flight_time)
                    # 滤波: min_flight_time — 低于下限的腾空合并到接触时间
                    elif cfg.min_flight_time > 0 and air_time * 1000 < cfg.min_flight_time:
                        log.debug("air_time %.1fms < min_flight_time %dms, merged to contact",
                                  air_time * 1000, cfg.min_flight_time)
                        if self.contact_times:
                            self.contact_times[-1] += air_time
                    else:
                        self.air_times.append(air_time)
                        ev._air_time = air_time
                        ev._hop_height = 0.5 * G * (air_time / 2) ** 2
                        ev._contact_time = self.contact_times[-1] if self.contact_times else None
            if self.last_touch_time is not None:
                cycle = ev.time - self.last_touch_time
                if cycle > 0:
                    self.cycle_times.append(cycle)
            self.last_touch_time = ev.time

            # 检查自动停止条件
            self._check_stop_condition()

        elif ev.kind.lower() == "lift":
            self.lift_count += 1
            if self.last_touch_time is not None:
                contact_time = ev.time - self.last_touch_time
                if contact_time > 0:
                    # 滤波: min_contact_time — 低于下限的接触合并到关联腾空时间
                    if cfg.min_contact_time > 0 and contact_time * 1000 < cfg.min_contact_time:
                        log.debug("contact_time %.1fms < min_contact_time %dms, merged to flight",
                                  contact_time * 1000, cfg.min_contact_time)
                        if self.air_times:
                            self.air_times[-1] += contact_time
                    else:
                        self.contact_times.append(contact_time)
            self.last_lift_time = ev.time

    # ---------------------------------------------------------------
    #  步态模式处理
    # ---------------------------------------------------------------

    def _process_gait(self, bits: list, rel_time: float, abs_time: float):
        """步态分析模式：ClusterTracker + ContactBasedGaitTracker"""
        clusters = extract_clusters(bits)
        self._cluster_tracker.update(rel_time, clusters)

        active_tracks = self._cluster_tracker.get_active_tracks_view()
        events = self._contact_tracker.process_frame(rel_time, active_tracks)

        # 同步计数器
        self.touch_count = self._contact_tracker.touch_count
        self.lift_count = self._contact_tracker.lift_count

        # 发射高级事件 (低频: 仅在 touch/lift 发生时)
        for ev in events:
            self.gait_step_event.emit(ev)  # → UI

        # 周期性状态快照 (节流 ~10Hz)
        if abs_time - self._last_snapshot_ts >= self._snapshot_interval:
            self._emit_gait_snapshot(rel_time, clusters)
            self._last_snapshot_ts = abs_time

    def _emit_gait_snapshot(self, rel_time: float, clusters: list):
        """构建步态状态快照 dict 并发射给 UI"""
        ct = self._contact_tracker
        active_count = len(ct.foot_contact_queue)

        if active_count == 0:
            status = "腾空 / 离地"
        elif active_count == 1:
            status = "单脚支撑"
        else:
            status = f"多支撑 ({active_count}脚)"

        # 活跃脚印坐标
        active_centroids = []
        for cid in ct.foot_contact_queue:
            if cid in ct.active_contacts:
                c = ct.active_contacts[cid].latest_centroid
                if c is not None:
                    active_centroids.append(c)

        snapshot = {
            "timestamp": rel_time,
            "status": status,
            "cluster_count": len(clusters),
            "active_centroids": active_centroids,
            "touch_count": self.touch_count,
            "lift_count": self.lift_count,
            # 步长统计
            "stride_count": ct.stride_count,
            "stride_sum": ct.stride_sum,
            "latest_stride": ct.stride_lengths[-1] if ct.stride_lengths else None,
            # 步速统计
            "velocity_count": ct.velocity_count,
            "velocity_sum": ct.velocity_sum,
            "latest_velocity": ct.velocities[-1] if ct.velocities else None,
            # 支撑时间
            "foot_a_support_times": list(ct.foot_a_support_times),
            "foot_b_support_times": list(ct.foot_b_support_times),
            # 高阶指标
            "latest_extra_metrics": dict(ct.latest_extra_metrics) if ct.latest_extra_metrics else {},
        }
        self.gait_status_snapshot.emit(snapshot)

    # ---------------------------------------------------------------
    #  自动停止逻辑
    # ---------------------------------------------------------------

    def _check_stop_condition(self):
        """在每次 touch 事件后检查是否满足自动结束条件。"""
        if self._finished:
            return

        cfg = self._config

        # Status change + number_of_jumps: 跳够指定次数
        if cfg.stop_type == "Status change" and cfg.number_of_jumps:
            if self.touch_count >= cfg.number_of_jumps:
                self._finished = True
                log.info("自动停止: 已完成 %d/%d 次跳跃",
                         self.touch_count, cfg.number_of_jumps)
                self.test_finished.emit("jump_count_reached")

    def _start_timer(self):
        """如果 stop_type=End of Time，启动倒计时。在 set_start_time 中调用。"""
        if self._config.stop_type != "End of Time":
            return

        seconds = self._config.get_test_length_seconds()
        if not seconds or seconds <= 0:
            log.warning("stop_type=End of Time 但 test_length 无效: %s",
                        self._config.test_length)
            return

        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._on_timer_expired)
        self._stop_timer.start(seconds * 1000)
        log.info("倒计时启动: %d 秒", seconds)

    def _on_timer_expired(self):
        """End of Time 倒计时到期。"""
        if self._finished:
            return
        self._finished = True
        log.info("自动停止: 测试时间到")
        self.test_finished.emit("time_up")


__all__ = ["GaitEngine"]
