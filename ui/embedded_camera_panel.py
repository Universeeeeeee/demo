"""Embedded camera preview panel for the execution view."""

from __future__ import annotations

import time
from typing import Optional

import numpy as np
from qtpy.QtCore import QThread, Qt
from qtpy.QtGui import QImage, QPixmap
from qtpy.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QVBoxLayout

from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton


class EmbeddedCameraPanel(QFrame):
    """Compact camera preview shell that reuses the existing camera captures."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._camera_type = "tinyse"
        self._thread: Optional[QThread] = None
        self._capture = None
        self._record_path: Optional[str] = None
        self._preview_start_time: Optional[float] = None
        self._preview_active = False

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
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self._title = MLabel("OBSBOT Tiny SE")
        self._title.setStyleSheet("font-size: 10pt; color: #a8a8a8;")
        header.addWidget(self._title)
        header.addStretch()

        self._btn_settings = MPushButton("⚙")
        self._btn_settings.setFixedSize(32, 30)
        self._btn_settings.setToolTip("摄像头设置")
        self._btn_settings.setStyleSheet(
            "font-size: 13pt; padding: 0; "
            "background-color: #3b3b3b; border: 1px solid #555; border-radius: 5px;"
        )
        self._menu = QMenu(self)
        self._record_action = self._menu.addAction("Record")
        self._record_action.triggered.connect(self._on_record)
        self._menu.aboutToShow.connect(self._refresh_menu)
        self._btn_settings.setMenu(self._menu)
        header.addWidget(self._btn_settings)
        layout.addLayout(header)

        self._preview = QLabel("未连接相机")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumSize(480, 320)
        self._preview.setStyleSheet(
            "background-color: #111; color: #888; border: 1px solid #303036;"
        )
        layout.addWidget(self._preview, 1)

        footer = QHBoxLayout()
        self._stats = MLabel("Idle")
        self._stats.setStyleSheet("font-size: 9pt; color: #9a9a9a;")
        footer.addWidget(self._stats, 1)

        self._btn_start = MPushButton("Start Preview").primary()
        self._btn_start.setFixedHeight(30)
        self._btn_start.setStyleSheet("font-size: 10pt; padding: 2px 10px;")
        self._btn_start.clicked.connect(self.start_preview)
        footer.addWidget(self._btn_start)

        self._btn_stop = MPushButton("Stop Preview")
        self._btn_stop.setFixedHeight(30)
        self._btn_stop.setStyleSheet("font-size: 10pt; padding: 2px 10px;")
        self._btn_stop.clicked.connect(self.stop_preview)
        footer.addWidget(self._btn_stop)
        layout.addLayout(footer)

    def set_camera_type(self, camera_type: str):
        if camera_type == self._camera_type:
            return
        was_running = self._preview_active
        self.shutdown()
        self._camera_type = camera_type
        self._title.setText(self._camera_title())
        self._preview.setText("未连接相机")
        self._stats.setText("Idle")
        if was_running:
            self.start_preview()

    def start_preview(self):
        if self._thread is not None:
            if hasattr(self._capture, "set_preview_enabled"):
                self._capture.set_preview_enabled(True)
            self._preview_active = True
            self._preview_start_time = time.perf_counter()
            self._set_running(True)
            return

        try:
            capture = self._create_capture()
        except Exception as exc:
            self._on_error(str(exc))
            return

        thread = QThread(self)
        capture.moveToThread(thread)
        capture.frame_ready.connect(self._on_frame)
        capture.stats_updated.connect(self._on_stats)
        capture.recording_finished.connect(self._on_recording_finished)
        capture.error.connect(self._on_error)
        thread.started.connect(capture.start)
        thread.finished.connect(capture.deleteLater)

        self._thread = thread
        self._capture = capture
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
        self._stats.setText("Idle")
        self._preview.setText("已停止")

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
        scale = min(target.width() / w, target.height() / h, 1.0)
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

    def _on_stats(self, fps: float, record_sec: float):
        if not self._preview_active:
            return
        rec = f"  |  REC {record_sec:.1f}s" if record_sec > 0 else ""
        self._stats.setText(f"Capture {fps:.2f} fps{rec}")

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
        self._stats.setText(f"Saved: {path}")
        self._refresh_menu()

    def _on_error(self, message: str):
        self._preview.setText("未连接相机")
        self._stats.setText(f"Error: {message}")
        self.shutdown()

    def _refresh_menu(self):
        capture = self._capture
        running = self._preview_active and capture is not None
        busy = self._is_record_busy(capture) if capture is not None else False
        recording = self._is_recording(capture) if capture is not None else False
        self._record_action.setEnabled(running and not (busy and not recording))
        if busy and not recording:
            self._record_action.setText("Saving...")
        elif recording:
            self._record_action.setText("Stop Recording")
        else:
            self._record_action.setText("Record")

    def _set_running(self, running: bool):
        self._btn_start.setEnabled(not running)
        self._btn_stop.setEnabled(running)
        self._refresh_menu()

    def _camera_title(self) -> str:
        if self._camera_type == "logi":
            return "Logitech MX Brio"
        if self._camera_type == "basic":
            return "基础预览"
        return "OBSBOT Tiny SE"

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
