"""
session_controller.py — 测试会话控制器

独立的 QObject 子类，专注管理一次测试会话的硬件资源生命周期:
  - 创建/销毁 QThread + UsbWorker + GaitEngine
  - 转发 GaitEngine 信号给 View 层
  - 测试结束时构造 TestReport 并发射

设计约束:
  - 不 import 任何 QtWidgets，不知道界面长什么样
  - 不持有任何 View 引用
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from qtpy.QtCore import QObject, Signal, Slot, QThread, Qt

from config.test_config import AnyTestConfig, TestConfig
from config.test_report import TestReport, build_report
from hardware.usb_worker import UsbWorker
from engine.gait_engine import GaitEngine
from path_utils import find_dll as _find_dll

log = logging.getLogger(__name__)


class SessionController(QObject):
    """
    管理一次测试会话的完整生命周期。

    信号流::

        MainWindow → prepare(config) → 创建后台资源
        MainWindow → start()         → 启动线程
        GaitEngine → hop_event       → 转发给 ExecutionView
        GaitEngine → test_finished   → stop() → 构造 TestReport → session_finished
    """

    # ---- 转发给 ExecutionView 的实时数据信号 ----
    hop_event = Signal(object)              # FootEvent (纵跳)
    gait_step_event = Signal(object)        # GaitStepEvent (步态)
    gait_snapshot = Signal(dict)            # 步态状态快照 (~10Hz)
    device_message = Signal(str)            # 设备消息 (节流)

    # ---- 生命周期信号 → MainWindow ----
    session_started = Signal()
    session_finished = Signal(object)       # TestReport

    def __init__(self, parent=None):
        super().__init__(parent)

        # 后台资源 (懒初始化)
        self._thread: Optional[QThread] = None
        self._worker: Optional[UsbWorker] = None
        self._engine: Optional[GaitEngine] = None

        # USB 硬件参数
        self._dll_path = _find_dll()
        self._vid = self._parse_int_env("DAYU_VID", 0x04B4)
        self._pid = self._parse_int_env("DAYU_PID", 0x1004)
        self._timeout_ms = self._parse_int_env("DAYU_TIMEOUT", 30)
        self._chunk_size = self._parse_int_env("DAYU_CHUNK", 512)

        # 会话状态
        self._config: Optional[AnyTestConfig] = None
        self._start_time: Optional[float] = None
        self._finish_reason: Optional[str] = None
        self._is_running = False

    # ------------------------------------------------------------------
    #  公共方法
    # ------------------------------------------------------------------

    def prepare(self, config: AnyTestConfig):
        """创建后台资源（QThread + UsbWorker + GaitEngine），但不启动。

        调用此方法后，资源已就绪，等待 start() 启动线程。
        """
        # 如果有上一次的残留资源，先清理
        self._cleanup()

        self._config = config
        self._finish_reason = None

        # 1. 创建线程
        self._thread = QThread()

        # 2. 创建 L1: USB 采集层
        self._worker = UsbWorker(
            dll_path=self._dll_path,
            vid=self._vid,
            pid=self._pid,
            timeout_ms=self._timeout_ms,
            chunk_size=self._chunk_size,
        )
        self._worker.moveToThread(self._thread)

        # 3. 创建 L2: 算法引擎层
        self._engine = GaitEngine(config=config)
        self._engine.moveToThread(self._thread)

        # 4. 连接 L1 → L2 (同线程 DirectConnection, 零开销)
        self._worker.raw_contact_signal.connect(
            self._engine.process_raw_frame, Qt.DirectConnection
        )

        # 5. 连接 L2 → Controller (跨线程 QueuedConnection, 低频)
        self._engine.hop_event.connect(self._on_hop_event)
        self._engine.gait_step_event.connect(self._on_gait_step_event)
        self._engine.gait_status_snapshot.connect(self._on_gait_snapshot)
        self._engine.test_finished.connect(self._on_engine_finished)

        # 6. 连接 L1 → Controller (设备消息, 节流)
        self._worker.data_received.connect(self._on_device_message)

        # 7. 线程启动时 → 启动 USB 采集
        self._thread.started.connect(self._worker.start)
        self._thread.finished.connect(self._worker.deleteLater)

        log.info("Session prepared: %s", config.test_type)

    def start(self):
        """启动后台线程，开始数据采集。"""
        if self._thread is None:
            log.warning("start() called but no session prepared")
            return

        self._start_time = time.perf_counter()
        if self._engine:
            self._engine.set_start_time(self._start_time)

        self._is_running = True
        self._thread.start()
        self.session_started.emit()
        log.info("Session started")

    def pause(self):
        """暂停数据处理（引擎跳过帧，USB 继续采集）。"""
        if self._engine:
            self._engine.paused = True

    def resume(self):
        """恢复数据处理。"""
        if self._engine:
            self._engine.paused = False

    def stop(self):
        """停止会话，构造 TestReport 并发射 session_finished 信号。"""
        if not self._is_running:
            return

        self._is_running = False
        report = self._do_stop(self._finish_reason or "manual")

        if report is not None:
            self.session_finished.emit(report)

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def engine(self) -> Optional[GaitEngine]:
        """暴露引擎引用，供 ExecutionView 读取实时统计（如 touch_count）。"""
        return self._engine

    @property
    def config(self) -> Optional[AnyTestConfig]:
        return self._config

    @property
    def start_time(self) -> Optional[float]:
        return self._start_time

    # ------------------------------------------------------------------
    #  内部信号处理
    # ------------------------------------------------------------------

    @Slot(object)
    def _on_hop_event(self, ev):
        self.hop_event.emit(ev)

    @Slot(object)
    def _on_gait_step_event(self, ev):
        self.gait_step_event.emit(ev)

    @Slot(dict)
    def _on_gait_snapshot(self, snapshot):
        self.gait_snapshot.emit(snapshot)

    @Slot(str)
    def _on_device_message(self, msg):
        self.device_message.emit(msg)

    @Slot(str)
    def _on_engine_finished(self, reason: str):
        """GaitEngine 自动停止回调（跳跃次数达标 / 时间到）。"""
        log.info("Engine auto-stop: %s", reason)
        self._finish_reason = reason
        # 延迟执行 stop，确保最后一个事件处理完毕
        from qtpy.QtCore import QTimer
        QTimer.singleShot(200, self.stop)

    # ------------------------------------------------------------------
    #  内部实现
    # ------------------------------------------------------------------

    def _do_stop(self, reason: str) -> Optional[TestReport]:
        """执行实际的停止流程，返回 TestReport。"""
        engine = self._engine
        report = None

        # 1. 标记引擎完成 (防止后续回调)
        if engine is not None:
            engine._paused = True
            engine._finished = True
            # 停止引擎内部定时器
            if hasattr(engine, '_stop_timer') and engine._stop_timer:
                engine._stop_timer.stop()

        # 2. 停止 USB 采集
        if self._worker:
            try:
                self._worker.stop()
            except Exception:
                log.exception("Error stopping USB worker")

        # 3. 停止线程
        if self._thread:
            try:
                self._thread.quit()
                self._thread.wait(2000)
            except Exception:
                log.exception("Error stopping engine thread")

        # 4. 构造不可变报告 (在释放引用之前)
        if engine is not None:
            try:
                report = build_report(engine, reason)
            except Exception:
                log.exception("Error building report")

        # 5. 清理引用
        self._thread = None
        self._worker = None
        self._engine = None

        log.info("Session stopped: %s", reason)
        return report

    def _cleanup(self):
        """清理可能残留的上一次会话资源。"""
        if self._is_running:
            self._is_running = False
            self._do_stop("cleanup")

        self._thread = None
        self._worker = None
        self._engine = None

    @staticmethod
    def _parse_int_env(name: str, default: int) -> int:
        v = os.getenv(name)
        if not v:
            return default
        try:
            return int(v, 0)
        except Exception:
            return default
