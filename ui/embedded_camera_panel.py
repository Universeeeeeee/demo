"""Embedded camera preview panel for the execution view."""

from __future__ import annotations

import time
from typing import Optional

import numpy as np
from qtpy.QtCore import QThread, Qt
from qtpy.QtGui import QImage, QPixmap
from qtpy.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from dayu_widgets.check_box import MCheckBox
from dayu_widgets.combo_box import MComboBox
from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton


FOV_OPTIONS = {0: "86°", 1: "78°", 2: "65°"}
EXPOSURE_OPTIONS = {
    0: "+0.0 EV", 3: "+0.3", 7: "+0.7", 10: "+1.0", 13: "+1.3",
    17: "+1.7", 20: "+2.0", 23: "+2.3", 27: "+2.7", 30: "+3.0",
    -30: "-3.0", -27: "-2.7", -23: "-2.3", -20: "-2.0",
    -17: "-1.7", -13: "-1.3", -10: "-1.0", -7: "-0.7", -3: "-0.3",
}
AI_SUB_MODE = {0: "标准", 1: "上半身", 2: "特写", 3: "无头", 4: "下半身", 5: "Butt"}
WDR_OPTIONS = {0: "关闭", 1: "DOL 2→1", 2: "Sensor"}


class _AspectRatioContainer(QWidget):
    """Keep the child label at the largest exact 16:9 size that fits."""

    def __init__(self, preview: QLabel, parent=None):
        super().__init__(parent)
        self._preview = preview
        self._preview.setParent(self)
        self._overlay = None

    def set_overlay(self, overlay: QWidget):
        self._overlay = overlay
        self._overlay.setParent(self)
        self._layout_children()

    def _layout_children(self):
        rect = self.contentsRect()
        unit = max(1, min(rect.width() // 16, rect.height() // 9))
        width = unit * 16
        height = unit * 9
        left = rect.x() + (rect.width() - width) // 2
        top = rect.y() + (rect.height() - height) // 2
        self._preview.setGeometry(left, top, width, height)
        if self._overlay is not None:
            self._overlay.move(
                left + width - self._overlay.width() - 8,
                top + 8,
            )
            self._overlay.raise_()

    def resizeEvent(self, event):
        self._layout_children()
        super().resizeEvent(event)


class EmbeddedCameraPanel(QFrame):
    """Compact camera preview shell that reuses the existing camera captures."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._camera_type = "tinyse"
        self._thread: Optional[QThread] = None
        self._capture = None
        self._control = None
        self._record_path: Optional[str] = None
        self._preview_start_time: Optional[float] = None
        self._preview_active = False
        self._status_text = "Idle"

        self._build_ui()
        self._set_running(False)

    def _build_ui(self):
        self.setStyleSheet(
            "EmbeddedCameraPanel {"
            "  background-color: rgba(18, 18, 22, 0.92);"
            "  border: 1px solid rgba(90, 90, 95, 0.7);"
            "  border-radius: 8px;"
            "}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        self._preview = QLabel("未连接相机")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumSize(320, 180)
        self._preview.setStyleSheet(
            "background-color: #111; color: #888; border: none;"
        )
        self._preview_container = _AspectRatioContainer(self._preview)
        self._preview_container.setMinimumSize(320, 180)
        layout.addWidget(self._preview_container, 1)

        self._btn_settings = MPushButton("⚙")
        self._btn_settings.setFixedSize(30, 28)
        self._btn_settings.setToolTip("摄像头设置")
        self._btn_settings.setStyleSheet(
            "font-size: 13pt; padding: 0; "
            "background-color: #3b3b3b; border: 1px solid #555; border-radius: 5px;"
        )
        self._menu = QMenu(self)
        self._menu.setMinimumWidth(340)
        self._build_settings_controls()
        self._menu.addSeparator()
        self._restart_action = self._menu.addAction("重新启动预览")
        self._restart_action.triggered.connect(self._restart_preview)
        self._record_action = self._menu.addAction("Record")
        self._record_action.triggered.connect(self._on_record)
        self._menu.aboutToShow.connect(self._refresh_menu)
        self._btn_settings.setMenu(self._menu)
        self._preview_container.set_overlay(self._btn_settings)

    def _build_settings_controls(self):
        panel = QWidget(self._menu)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        row = QHBoxLayout()
        self._chk_mirror = MCheckBox("镜像")
        self._chk_mirror.stateChanged.connect(self._on_mirror)
        row.addWidget(self._chk_mirror)
        self._cmb_fov = MComboBox()
        for value, label in FOV_OPTIONS.items():
            self._cmb_fov.addItem(label, value)
        self._cmb_fov.currentIndexChanged.connect(self._on_fov_changed)
        row.addWidget(MLabel("视野:"))
        row.addWidget(self._cmb_fov)
        layout.addLayout(row)

        row = QHBoxLayout()
        self._cmb_ai = MComboBox()
        for value, label in sorted(AI_SUB_MODE.items()):
            self._cmb_ai.addItem(label, value)
        self._cmb_ai.setCurrentIndex(4)
        row.addWidget(MLabel("AI 追踪:"))
        row.addWidget(self._cmb_ai)
        self._btn_ai_go = MPushButton("激活")
        self._btn_ai_go.clicked.connect(self._on_ai_go)
        row.addWidget(self._btn_ai_go)
        self._btn_ai_off = MPushButton("关闭")
        self._btn_ai_off.clicked.connect(self._on_ai_off)
        row.addWidget(self._btn_ai_off)
        layout.addLayout(row)

        row = QHBoxLayout()
        self._chk_af = MCheckBox("自动对焦")
        self._chk_af.setChecked(True)
        self._chk_af.stateChanged.connect(self._on_af_changed)
        row.addWidget(self._chk_af)
        self._cmb_exp = MComboBox()
        for value, label in sorted(EXPOSURE_OPTIONS.items()):
            self._cmb_exp.addItem(label, value)
        self._cmb_exp.setCurrentIndex(self._cmb_exp.findData(0))
        self._cmb_exp.currentIndexChanged.connect(self._on_exp_changed)
        row.addWidget(MLabel("曝光:"))
        row.addWidget(self._cmb_exp)
        layout.addLayout(row)

        row = QHBoxLayout()
        self._cmb_flicker = MComboBox()
        self._cmb_flicker.addItem("60Hz", 0)
        self._cmb_flicker.addItem("50Hz", 1)
        self._cmb_flicker.currentIndexChanged.connect(self._on_flicker_changed)
        row.addWidget(MLabel("抗频闪:"))
        row.addWidget(self._cmb_flicker)
        self._cmb_wdr = MComboBox()
        for value, label in WDR_OPTIONS.items():
            self._cmb_wdr.addItem(label, value)
        self._cmb_wdr.currentIndexChanged.connect(self._on_wdr_changed)
        row.addWidget(MLabel("HDR:"))
        row.addWidget(self._cmb_wdr)
        layout.addLayout(row)

        self._controls_action = QWidgetAction(self._menu)
        self._controls_action.setDefaultWidget(panel)
        self._menu.addAction(self._controls_action)

    def set_camera_type(self, camera_type: str):
        if camera_type == self._camera_type:
            return
        was_running = self._preview_active
        self.shutdown()
        self._camera_type = camera_type
        self._preview.setText("未连接相机")
        self._set_status("Idle")
        if was_running:
            self.start_preview()

    def start_preview(self):
        self._preview.setText("正在连接相机")
        if self._thread is not None:
            if hasattr(self._capture, "set_preview_enabled"):
                self._capture.set_preview_enabled(True)
            self._preview_active = True
            self._preview_start_time = time.perf_counter()
            self._set_running(True)
            return

        if self._camera_type == "tinyse":
            self._ensure_control()
        try:
            capture = self._create_capture()
        except Exception as exc:
            self._on_error(str(exc))
            return

        thread = QThread(self)
        capture.moveToThread(thread)
        capture.frame_ready.connect(self._on_frame)
        capture.recording_finished.connect(self._on_recording_finished)
        capture.error.connect(self._on_error)
        thread.started.connect(capture.start)
        thread.finished.connect(capture.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        self._capture = capture
        if hasattr(capture, "set_mirror"):
            capture.set_mirror(self._chk_mirror.isChecked())
        self._preview_active = True
        self._preview_start_time = time.perf_counter()
        thread.start()
        self._set_running(True)

    def stop_preview(self):
        capture = self._capture
        if capture is not None:
            if self._is_recording(capture):
                self._stop_record(capture)
            if hasattr(capture, "set_preview_enabled"):
                capture.set_preview_enabled(False)
        self._preview_active = False
        self._preview_start_time = None
        self._set_running(False)
        self._set_status("Idle")
        self._preview.setText("已停止")

    def _restart_preview(self):
        self.shutdown()
        self.start_preview()

    def shutdown(self):
        capture = self._capture
        thread = self._thread
        if capture is not None:
            if self._is_record_busy(capture):
                self._stop_record(capture, wait=True)
            capture.stop()
        if thread is not None:
            thread.quit()
            thread.wait(2000)
        self._thread = None
        self._capture = None
        self._preview_active = False
        self._preview_start_time = None
        self._record_path = None
        self._release_control()
        self._set_running(False)

    def _create_capture(self):
        if self._camera_type == "tinyse":
            from camera.tinyse_camera import TinySeCameraCapture

            return TinySeCameraCapture()
        if self._camera_type == "logi":
            from camera.logi_camera import CAMERA_INDEX, CameraCapture

            capture = CameraCapture()
            if not capture.open(CAMERA_INDEX):
                raise RuntimeError("无法打开 MX Brio，请检查连接。")
            return capture
        raise RuntimeError("基础预览暂未嵌入，请选择 MX Brio 或 Tiny SE。")

    def _on_frame(self, frame: np.ndarray):
        if not self._preview_active:
            return
        import cv2

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        target = self._preview.size()
        scale = min(target.width() / w, target.height() / h)
        disp_w = max(1, int(w * scale))
        disp_h = max(1, int(h * scale))
        if disp_w != w or disp_h != h:
            rgb = cv2.resize(rgb, (disp_w, disp_h), interpolation=cv2.INTER_AREA)
        bytes_per_line = rgb.strides[0]
        image = QImage(
            rgb.data,
            rgb.shape[1],
            rgb.shape[0],
            bytes_per_line,
            QImage.Format_RGB888,
        ).copy()
        self._preview.setPixmap(QPixmap.fromImage(image))
        self._preview_start_time = None

    def _on_record(self):
        capture = self._capture
        if capture is None:
            return
        if self._is_record_busy(capture) and not self._is_recording(capture):
            return
        if not self._is_recording(capture):
            path = capture.start_record()
            if path:
                self._record_path = path
        else:
            self._stop_record(capture)
        self._refresh_menu()

    def _on_recording_finished(self, path: str):
        self._record_path = None
        self._set_status(f"Saved: {path}")
        self._refresh_menu()

    def _on_error(self, message: str):
        self._preview.setText("未连接相机")
        self._set_status(f"Error: {message}")
        self.shutdown()

    def _apply_control_settings(self, control):
        control.set_fov(int(self._cmb_fov.currentData() or 0))
        control.set_auto_focus(self._chk_af.isChecked())
        control.set_exposure_compensation(int(self._cmb_exp.currentData() or 0))
        control.set_anti_flicker(int(self._cmb_flicker.currentData() or 0))
        control.set_wdr(int(self._cmb_wdr.currentData() or 0))
        control.set_ai_off()

    def _ensure_control(self, apply_settings: bool = True) -> bool:
        if self._control is not None:
            if apply_settings:
                self._apply_control_settings(self._control)
            return True
        try:
            from camera.tinyse_camera import TinySeCameraControl

            control = TinySeCameraControl(0)
            if not control.init():
                control.close()
                self._set_status("SDK 控制不可用: 未检测到 Tiny SE")
                return False
            self._control = control
            if apply_settings:
                self._apply_control_settings(control)
            return True
        except Exception as exc:
            self._control = None
            self._set_status(f"SDK 控制不可用: {exc}")
            return False

    def _release_control(self):
        control = self._control
        self._control = None
        if control is not None:
            control.close()

    def _report_control_result(self, action: str, result: int):
        if result < 0:
            self._set_status(f"{action}失败，返回码: {result}")

    def _set_status(self, text: str):
        self._status_text = text
        tooltip = "摄像头设置"
        if text != "Idle":
            tooltip = f"{tooltip}\n{text}"
        self._btn_settings.setToolTip(tooltip)

    def _on_mirror(self, _state: int):
        if self._capture is not None and hasattr(self._capture, "set_mirror"):
            self._capture.set_mirror(self._chk_mirror.isChecked())

    def _on_fov_changed(self, _index: int):
        if self._control is not None:
            self._control.set_fov(int(self._cmb_fov.currentData()))

    def _on_ai_go(self):
        if self._ensure_control(apply_settings=False):
            result = self._control.set_ai_mode(int(self._cmb_ai.currentData()))
            self._report_control_result("AI 追踪", result)

    def _on_ai_off(self):
        if self._ensure_control(apply_settings=False):
            self._report_control_result("关闭 AI 追踪", self._control.set_ai_off())

    def _on_af_changed(self, _state: int):
        if self._control is not None:
            self._control.set_auto_focus(self._chk_af.isChecked())

    def _on_exp_changed(self, _index: int):
        if self._control is not None:
            self._control.set_exposure_compensation(int(self._cmb_exp.currentData()))

    def _on_flicker_changed(self, _index: int):
        if self._control is not None:
            self._control.set_anti_flicker(int(self._cmb_flicker.currentData()))

    def _on_wdr_changed(self, _index: int):
        if self._control is not None:
            self._control.set_wdr(int(self._cmb_wdr.currentData()))

    def _refresh_menu(self):
        capture = self._capture
        running = self._preview_active and capture is not None
        self._controls_action.setEnabled(self._camera_type == "tinyse")
        busy = self._is_record_busy(capture) if capture is not None else False
        recording = self._is_recording(capture) if capture is not None else False
        self._record_action.setEnabled(running and not (busy and not recording))
        if busy and not recording:
            self._record_action.setText("Saving...")
        elif recording:
            self._record_action.setText("Stop Recording")
        else:
            self._record_action.setText("Record")

    def _set_running(self, _running: bool):
        self._refresh_menu()

    def _is_recording(self, capture) -> bool:
        if hasattr(capture, "is_recording"):
            return bool(capture.is_recording)
        return bool(getattr(capture, "_recording", False))

    def _is_record_busy(self, capture) -> bool:
        if hasattr(capture, "is_record_busy"):
            return bool(capture.is_record_busy)
        return self._is_recording(capture)

    def _stop_record(self, capture, wait: bool = False):
        try:
            capture.stop_record(wait=wait)
        except TypeError:
            capture.stop_record()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
