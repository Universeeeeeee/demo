"""
main_window.py — 多视图主窗口

纯粹的视图路由器 + 全局事件处理。
硬件资源管理委托给 SessionController。

使用方式::

    python ui/main_window.py
"""

from __future__ import annotations

import logging
import os
import sys

# Ensure project root is importable when running `python ui/main_window.py`.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QMainWindow, QStackedWidget, QMessageBox,
)
from dayu_widgets import dayu_theme
from dayu_widgets.qt import application

from config.test_config import TestConfig
from config.test_report import TestReport
from data.subject_store import SubjectProfile, SubjectStore
from ui.session_controller import SessionController
from ui.views.setup_view import SessionSetup, SetupView
from ui.views.execution_view import ExecutionView
from ui.views.report_view import ReportView
from ui.llm_client import LLMWorkerClient

# Camera (可选)
try:
    from ui.camera import Camera
except ImportError:
    Camera = None

# 专用相机 widget + 检测工具
try:
    from camera.logi_camera import LogiCameraWidget
except ImportError:
    LogiCameraWidget = None

try:
    from camera.tinyse_camera import TinySeCameraWidget
except ImportError:
    TinySeCameraWidget = None

try:
    from camera.tinyse_dshow_capture import TinySeDShowCapture
except ImportError:
    TinySeDShowCapture = None

import cv2
from qtpy.QtCore import QTimer


log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """
    多视图主窗口。

    职责:
      - 持有 QStackedWidget，管理 3 个 View 的切换
      - 持有 SessionController，委托硬件资源管理
      - 处理相机打开/关闭
      - 处理测试结束后的临时汇总 (Phase 5a, ReportView 在 5b 中加入)
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Iron Jump — 步态分析系统")
        self.setMinimumSize(1100, 700)
        self.resize(1200, 750)

        # ===== Controller =====
        self._controller = SessionController(self)

        try:
            self._subject_store: SubjectStore | None = SubjectStore()
        except Exception:
            log.exception("Failed to initialize subject store")
            self._subject_store = None

        self._active_config: TestConfig | None = None
        self._subject_id: int | None = None
        self._subject: SubjectProfile | None = None

        # ===== Views =====
        self._stack = QStackedWidget() 
        self.setCentralWidget(self._stack)

        self._llm_client = LLMWorkerClient(
            python_exe=sys.executable,
            worker_script=os.path.join(_project_root, "agent", "llm_worker.py"),
        )
        self._setup_view = SetupView(subject_store=self._subject_store, llm_client=self._llm_client)
        self._exec_view = ExecutionView()
        self._report_view = ReportView()

        self._stack.addWidget(self._setup_view)     # index 0
        self._stack.addWidget(self._exec_view)      # index 1
        self._stack.addWidget(self._report_view)    # index 2

        # ===== Camera =====
        self._logi_camera = None
        self._tinyse_camera = None
        self._basic_camera = None

        # ===== 连接信号 =====
        self._connect_signals()

        # ===== 初始页面 =====
        self._go_to_setup()

        # ===== 异步检测相机设备 =====
        QTimer.singleShot(0, self._detect_cameras)

        # ===== LLM Worker 健康检查 =====
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._check_llm_health)
        self._health_timer.start(5000)
        self._health_fail_count = 0

    # ------------------------------------------------------------------
    #  信号连接
    # ------------------------------------------------------------------

    def _connect_signals(self):
        # SetupView → MainWindow
        self._setup_view.ready_signal.connect(self._on_ready)

        # ExecutionView 控制 → MainWindow / Controller
        self._exec_view.start_requested.connect(self._on_start)
        self._exec_view.pause_requested.connect(self._on_pause)
        self._exec_view.stop_requested.connect(self._on_manual_stop)
        self._exec_view.camera_requested.connect(self._on_camera)

        # Controller 实时数据 → ExecutionView (直连)
        self._controller.hop_event.connect(self._exec_view.on_hop_event)
        self._controller.gait_step_event.connect(self._exec_view.on_gait_step_event)
        self._controller.gait_snapshot.connect(self._exec_view.on_gait_snapshot)
        self._controller.device_message.connect(self._exec_view.on_device_message)

        # Controller 生命周期 → MainWindow
        self._controller.session_finished.connect(self._on_session_finished)

        # ReportView → MainWindow
        self._report_view.return_home.connect(self._go_to_setup)
        self._report_view.export_requested.connect(lambda: None)  # export handled internally

    # ------------------------------------------------------------------
    #  视图切换
    # ------------------------------------------------------------------

    def _go_to_setup(self):
        self._active_config = None
        self._subject_id = None
        self._subject = None
        self._stack.setCurrentWidget(self._setup_view)

    def _go_to_execution(self):
        self._stack.setCurrentWidget(self._exec_view)

    def _go_to_report(self):
        self._stack.setCurrentWidget(self._report_view)

    # ------------------------------------------------------------------
    #  事件处理
    # ------------------------------------------------------------------

    def _on_ready(self, setup: SessionSetup):
        """SetupView '准备就绪' → 初始化资源 + 切到 ExecutionView"""
        config = setup.config
        self._active_config = config
        self._subject_id = setup.subject_id
        self._subject = setup.subject
        self._exec_view.reset()
        self._exec_view.configure(config)
        self._controller.prepare(config)
        self._go_to_execution()

    def _on_start(self):
        """ExecutionView '开始采集' → 启动 Controller"""
        self._controller.start()

    def _on_pause(self):
        """ExecutionView '暂停/继续' → 切换 Controller 暂停状态"""
        if self._controller.engine:
            if self._controller.engine.paused:
                self._controller.resume()
            else:
                self._controller.pause()

    def _on_manual_stop(self):
        """ExecutionView '结束' → 手动停止"""
        self._controller.stop()

    def _on_session_finished(self, report: TestReport):
        """Controller 发来 TestReport → 切到 ReportView"""
        if (
            self._subject_store is not None
            and self._subject_id is not None
            and self._active_config is not None
        ):
            try:
                self._subject_store.record_session(
                    self._subject_id,
                    self._active_config,
                    report,
                    height_cm=self._subject.height_cm if self._subject else None,
                    weight_kg=self._subject.weight_kg if self._subject else None,
                )
            except Exception:
                log.exception("Failed to record subject session")

        self._report_view.load_report(report)
        self._go_to_report()

    def _detect_cameras(self):
        """异步检测可用相机设备, 控制 Tiny SE 按钮显隐。"""
        has_tinyse = False
        try:
            probe = TinySeDShowCapture(device_needle="OBSBOT Tiny SE")
            probe.close()
            has_tinyse = True
        except Exception:
            log.exception("Tiny SE 检测失败")

        self._exec_view.set_tinyse_available(has_tinyse)

    def _check_llm_health(self):
        if not self._llm_client.is_running:
            return
        status = self._llm_client.worker_status(timeout=0.25)
        if status == "ready":
            self._health_fail_count = 0
        elif status in {"starting", "warming"}:
            return
        else:
            self._health_fail_count += 1
            if self._health_fail_count >= 2:
                log.warning("LLM worker health check failed twice, status=%s, stopping", status)
                self._llm_client.stop()
                self._health_fail_count = 0

    def _on_camera(self, camera_type: str):
        """根据 camera_type 打开/关闭对应相机窗口。
        
        支持三种类型: "logi" / "tinyse" / "basic"
        惰性创建, 已打开则置顶, 已销毁则重建。
        """
        if camera_type == "logi":
            if LogiCameraWidget is None:
                QMessageBox.warning(self, "相机", "LogiCameraWidget 模块不可用")
                return
            widget = self._logi_camera
            if widget is None:
                self._logi_camera = LogiCameraWidget()
                dayu_theme.apply(self._logi_camera)
                self._logi_camera.show()
            elif widget.isVisible():
                widget.raise_()
                widget.activateWindow()
                if widget.isMinimized():
                    widget.showNormal()
            else:
                # 已销毁则重建
                self._logi_camera = LogiCameraWidget()
                dayu_theme.apply(self._logi_camera)
                self._logi_camera.show()

        elif camera_type == "tinyse":
            if TinySeCameraWidget is None:
                QMessageBox.warning(self, "相机", "TinySeCameraWidget 模块不可用")
                return
            widget = self._tinyse_camera
            if widget is None:
                self._tinyse_camera = TinySeCameraWidget()
                dayu_theme.apply(self._tinyse_camera)
                self._tinyse_camera.show()
            elif widget.isVisible():
                widget.raise_()
                widget.activateWindow()
                if widget.isMinimized():
                    widget.showNormal()
            else:
                self._tinyse_camera = TinySeCameraWidget()
                dayu_theme.apply(self._tinyse_camera)
                self._tinyse_camera.show()

        elif camera_type == "basic":
            if Camera is None:
                QMessageBox.warning(self, "相机", "Camera 模块不可用")
                return
            cam = self._basic_camera
            if cam is None:
                cam = Camera()
                self._basic_camera = cam
            
            if not cam.is_running:
                cam.open_camera(threaded=True)
            else:
                cam.close_camera()
        else:
            log.warning(f"Unknown camera type: {camera_type}")

    # ------------------------------------------------------------------
    #  窗口关闭
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        """关闭窗口时清理所有资源。"""
        # 停止测试会话
        if self._controller.is_running:
            self._controller.stop()

        # 关闭相机
        try:
            if self._logi_camera is not None:
                self._logi_camera.close()
        except Exception:
            pass
        try:
            if self._tinyse_camera is not None:
                self._tinyse_camera.close()
        except Exception:
            pass
        try:
            if self._basic_camera is not None and self._basic_camera.is_running:
                self._basic_camera.close_camera()
        except Exception:
            pass

        # 关闭 LLM worker
        if self._llm_client.is_running:
            self._health_timer.stop()
            self._llm_client.stop()

        event.accept()


# ======================================================================
#  独立运行入口
# ======================================================================

if __name__ == "__main__":
    with application() as app:
        win = MainWindow()
        dayu_theme.apply(win)
        win.show()

        # 居中到屏幕 (防止 dayu_theme 导致窗口偏移到屏幕外)
        screen = app.primaryScreen().availableGeometry()
        win.move(
            (screen.width() - win.width()) // 2,
            (screen.height() - win.height()) // 2,
        )
