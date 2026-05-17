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

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QMainWindow, QStackedWidget, QMessageBox,
)
from dayu_widgets import dayu_theme
from dayu_widgets.qt import application

# 确保项目根目录在 sys.path 中
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from config.test_config import TestConfig
from config.test_report import TestReport
from data.subject_store import SubjectProfile, SubjectStore
from ui.session_controller import SessionController
from ui.views.setup_view import SessionSetup, SetupView
from ui.views.execution_view import ExecutionView
from ui.views.report_view import ReportView

# Camera (可选)
try:
    from ui.camera import Camera
except ImportError:
    Camera = None


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

        self._setup_view = SetupView(subject_store=self._subject_store)
        self._exec_view = ExecutionView()
        self._report_view = ReportView()

        self._stack.addWidget(self._setup_view)     # index 0
        self._stack.addWidget(self._exec_view)      # index 1
        self._stack.addWidget(self._report_view)    # index 2

        # ===== Camera =====
        self._camera = None

        # ===== 连接信号 =====
        self._connect_signals()

        # ===== 初始页面 =====
        self._go_to_setup()

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

    def _on_camera(self):
        """打开/关闭相机"""
        if Camera is None:
            QMessageBox.warning(self, "相机", "Camera 模块不可用")
            return

        if self._camera is None:
            self._camera = Camera()

        if not self._camera.is_running:
            self._camera.open_camera(threaded=True)
        else:
            self._camera.close_camera()

    # ------------------------------------------------------------------
    #  窗口关闭
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        """关闭窗口时清理所有资源。"""
        # 停止测试会话
        if self._controller.is_running:
            self._controller.stop()

        # 关闭相机
        if self._camera and self._camera.is_running:
            self._camera.close_camera()

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
