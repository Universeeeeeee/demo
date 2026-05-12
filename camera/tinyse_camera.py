"""
tinyse_camera.py — OBSBOT Tiny SE 摄像头独立预览窗口

基于 dayu_widgets + qtpy + DirectShow 后端。
为步态分析系统提供实时视觉参考。

使用方式::

    python camera/tinyse_camera.py

设计目标:
- 独立运行，不与 ui/ 目录现有模块耦合
- 后期可导入主界面嵌入
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from qtpy.QtCore import QObject, QThread, Signal, Qt
from qtpy.QtGui import QImage, QPixmap
from qtpy.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from dayu_widgets import dayu_theme
from dayu_widgets.check_box import MCheckBox
from dayu_widgets.collapse import MSectionItem
from dayu_widgets.combo_box import MComboBox
from dayu_widgets.divider import MDivider
from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton
from dayu_widgets.qt import application

try:
    from .tinyse_dshow_capture import TinySeDShowCapture
except ImportError:
    from tinyse_dshow_capture import TinySeDShowCapture

BIN_DIR = Path(__file__).resolve().parent / "bin"
WRAPPER_DLL = BIN_DIR / "obsbot_c_api.dll"

FOV_OPTIONS = {0: "86°", 1: "78°", 2: "65°"}
EXPOSURE_OPTIONS = {
    0: "+0.0 EV", 3: "+0.3", 7: "+0.7", 10: "+1.0", 13: "+1.3", 17: "+1.7", 20: "+2.0",
    23: "+2.3", 27: "+2.7", 30: "+3.0",
    -30: "-3.0", -27: "-2.7", -23: "-2.3", -20: "-2.0", -17: "-1.7",
    -13: "-1.3", -10: "-1.0", -7: "-0.7", -3: "-0.3",
}
AI_SUB_MODE = {0: "标准", 1: "上半身", 2: "特写", 3: "无头", 4: "下半身", 5: "Butt"}
WDR_OPTIONS = {0: "关闭", 1: "DOL 2→1", 2: "Sensor"}


FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
TARGET_FPS = 100
PREVIEW_FPS = 30
PREVIEW_WIDTH = 960
PREVIEW_HEIGHT = 540


def _bind_control_fns(dll: ctypes.CDLL) -> None:
    """为 DLL 绑定控制函数签名。"""
    dll.obsbot_refresh_devices.argtypes = [ctypes.c_int32]
    dll.obsbot_refresh_devices.restype = ctypes.c_int32
    dll.obsbot_close.argtypes = []
    dll.obsbot_close.restype = None
    for name in (
        "obsbot_set_camera_mirror",
        "obsbot_set_ai_mode",
        "obsbot_set_auto_focus",
        "obsbot_set_manual_focus",
        "obsbot_set_exposure_compensation",
        "obsbot_set_anti_flicker",
        "obsbot_set_fov",
        "obsbot_set_wdr",
    ):
        fn = getattr(dll, name)
        fn.argtypes = [ctypes.c_int32, ctypes.c_int32]
        fn.restype = ctypes.c_int32
    dll.obsbot_set_ai_mode.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]


class TinySeCameraControl:
    """Tiny SE SDK 参数控制。

    约束：SDK 和 DirectShow 不能同时占用 UVC 设备。
    所有设置必须在采集启动前完成，运行时修改无效。
    """

    def __init__(self, device_index: int = 0):
        if not WRAPPER_DLL.exists():
            raise FileNotFoundError(f"wrapper DLL not found: {WRAPPER_DLL}")
        os.add_dll_directory(str(BIN_DIR))
        self._dll = ctypes.CDLL(str(WRAPPER_DLL))
        _bind_control_fns(self._dll)
        self._idx = device_index
        self._dirty = False

    def init(self) -> bool:
        """采集前调用一次。填充设备缓存，返回是否成功。"""
        count = self._dll.obsbot_refresh_devices(500)
        if count <= 0:
            # 首次检测可能较慢，重试一次
            count = self._dll.obsbot_refresh_devices(5000)
        return count > 0

    def apply_pending(self):
        """应用所有待定设置（采集启动前调用一次）。"""
        self._dirty = False

    # ── 镜像 ──
    def set_mirror(self, on: bool) -> int:
        """硬件水平镜像。替代 cv2.flip。"""
        return self._dll.obsbot_set_camera_mirror(self._idx, 1 if on else 0)

    # ── AI 追踪 ──
    def set_ai_lower_body(self) -> int:
        """下半身追踪：AiWorkModeHuman(2) + AiSubModeLowerBody(4)。"""
        return self._dll.obsbot_set_ai_mode(self._idx, 2, 4)

    def set_ai_off(self) -> int:
        """关闭 AI 追踪。"""
        return self._dll.obsbot_set_ai_mode(self._idx, 0, 0)

    def set_ai_mode(self, sub_mode: int) -> int:
        """sub_mode: 0=标准 1=上半身 2=特写 3=无头 4=下半身 5=Butt"""
        return self._dll.obsbot_set_ai_mode(self._idx, 2, sub_mode)

    # ── 对焦 ──
    def set_auto_focus(self, on: bool) -> int:
        """on=True 自动对焦，on=False 手动对焦。"""
        return self._dll.obsbot_set_auto_focus(self._idx, 1 if on else 0)

    def set_manual_focus(self, value: int) -> int:
        """手动对焦值 0~100。"""
        return self._dll.obsbot_set_manual_focus(self._idx, value)

    # ── 曝光 ──
    def set_exposure_compensation(self, ev_index: int) -> int:
        """离散 EV 值，见 EXPOSURE_OPTIONS 白名单。"""
        return self._dll.obsbot_set_exposure_compensation(self._idx, ev_index)

    # ── 抗频闪 ──
    def set_anti_flicker(self, freq: int) -> int:
        """0=60Hz, 1=50Hz。"""
        return self._dll.obsbot_set_anti_flicker(self._idx, freq)

    # ── 视野 ──
    def set_fov(self, fov: int) -> int:
        """0=86°, 1=78°, 2=65°。"""
        return self._dll.obsbot_set_fov(self._idx, fov)

    # ── HDR/WDR ──
    def set_wdr(self, wdr: int) -> int:
        """0=Off, 1=DOL2to1, 2=Sensor。"""
        return self._dll.obsbot_set_wdr(self._idx, wdr)

    def close(self):
        """释放 SDK 资源。"""
        if self._dll is not None:
            self._dll.obsbot_close()
            self._dll = None


class TinySeCameraCapture(QObject):
    frame_ready = Signal(np.ndarray)
    stats_updated = Signal(float, float)
    recording_finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        device_needle: str = "OBSBOT Tiny SE",
        width: int = FRAME_WIDTH,
        height: int = FRAME_HEIGHT,
        fps: int = TARGET_FPS,
        preview_fps: int = PREVIEW_FPS,
        parent=None,
    ):
        super().__init__(parent)
        self._device_needle = device_needle
        self._width = width
        self._height = height
        self._fps = fps
        self._preview_interval = 1.0 / max(1, preview_fps)
        self._last_preview_time = 0.0
        self._capture: TinySeDShowCapture | None = None
        self._running = False
        self._recording = False
        self._record_path: Path | None = None
        self._record_start = 0.0
        self._mirror = True  # 软件镜像

    @property
    def is_recording(self) -> bool:
        return self._recording

    def open(self) -> bool:
        if self._capture is not None:
            return True
        try:
            self._capture = TinySeDShowCapture(
                device_needle=self._device_needle,
                width=self._width,
                height=self._height,
                fps=self._fps,
                on_frame=self._on_mjpg_frame,
            )
            return True
        except Exception as exc:
            self.error.emit(str(exc))
            self._capture = None
            return False

    def start(self):
        if not self.open():
            self._running = False
            return

        capture = self._capture
        if capture is None:
            self.error.emit("Tiny SE capture was not initialized")
            self._running = False
            return

        try:
            capture.start()
            self._running = True
            while self._running:
                stats = capture.stats()
                record_sec = time.perf_counter() - self._record_start if self._recording else 0.0
                self.stats_updated.emit(stats.wall_fps, record_sec)
                time.sleep(0.2)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self._cleanup()

    def stop(self):
        self._running = False
        if self._capture is not None:
            self._capture.stop()

    def start_record(self) -> str | None:
        if self._capture is None or self._recording:
            return None
        try:
            mjpg_path, _csv_path = self._capture.start_record()
        except Exception as exc:
            self.error.emit(str(exc))
            return None
        self._recording = True
        self._record_path = mjpg_path
        self._record_start = time.perf_counter()
        return str(mjpg_path)

    def stop_record(self):
        if self._capture is None or not self._recording:
            return
        path = self._record_path
        try:
            self._capture.stop_record()
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self._recording = False
            self._record_path = None
        if path is not None:
            self.recording_finished.emit(str(path))

    def set_mirror(self, on: bool):
        self._mirror = on

    def _on_mjpg_frame(self, data: bytes, _frame_index: int, _sample_time: float) -> None:
        now = time.perf_counter()
        if now - self._last_preview_time < self._preview_interval:
            return
        self._last_preview_time = now

        encoded = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if frame is None:
            return
        if self._mirror:
            frame = cv2.flip(frame, 1)
        self.frame_ready.emit(frame)

    def _cleanup(self):
        self._running = False
        if self._recording:
            self.stop_record()
        if self._capture is not None:
            self._capture.close()
            self._capture = None


class TinySeCameraWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OBSBOT Tiny SE")
        self.resize(1100, 860)
        screen = self.screen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )
        self._thread: QThread | None = None
        self._capture: TinySeCameraCapture | None = None
        self._control: TinySeCameraControl | None = None
        self._record_path: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(MDivider("OBSBOT Tiny SE"))

        self._preview = QLabel("Preview")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumSize(PREVIEW_WIDTH, PREVIEW_HEIGHT)
        self._preview.setStyleSheet("background: #111; color: #aaa;")
        layout.addWidget(self._preview)

        self._stats = MLabel("Idle")
        layout.addWidget(self._stats)

        buttons = QHBoxLayout()
        self._btn_start = MPushButton("Start Preview").primary()
        self._btn_stop = MPushButton("Stop")
        self._btn_record = MPushButton("Record")
        self._btn_stop.setEnabled(False)
        self._btn_record.setEnabled(False)
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_record.clicked.connect(self._on_record)
        buttons.addWidget(self._btn_start)
        buttons.addWidget(self._btn_stop)
        buttons.addWidget(self._btn_record)
        layout.addLayout(buttons)

        # ── 控制面板 ──
        ctl_container = QWidget()
        ctl = QVBoxLayout(ctl_container)
        ctl.setContentsMargins(8, 4, 8, 4)
        ctl.setSpacing(6)

        row1 = QHBoxLayout()
        self._chk_mirror = MCheckBox("镜像")
        self._chk_mirror.stateChanged.connect(self._on_mirror)
        row1.addWidget(self._chk_mirror)
        self._cmb_fov = MComboBox()
        for k, v in FOV_OPTIONS.items():
            self._cmb_fov.addItem(v, k)
        self._cmb_fov.currentIndexChanged.connect(self._on_fov_changed)
        row1.addWidget(MLabel("视野:"))
        row1.addWidget(self._cmb_fov)
        row1.addStretch()
        ctl.addLayout(row1)

        row2 = QHBoxLayout()
        self._cmb_ai = MComboBox()
        for k, v in sorted(AI_SUB_MODE.items()):
            self._cmb_ai.addItem(v, k)
        self._cmb_ai.setCurrentIndex(4)  # 默认下半身
        row2.addWidget(MLabel("AI 追踪:"))
        row2.addWidget(self._cmb_ai)
        self._btn_ai_go = MPushButton("激活")
        self._btn_ai_go.clicked.connect(self._on_ai_go)
        row2.addWidget(self._btn_ai_go)
        self._btn_ai_off = MPushButton("关闭追踪")
        self._btn_ai_off.clicked.connect(self._on_ai_off)
        row2.addWidget(self._btn_ai_off)
        row2.addStretch()
        ctl.addLayout(row2)

        row3 = QHBoxLayout()
        self._chk_af = MCheckBox("自动对焦")
        self._chk_af.setChecked(True)
        self._chk_af.stateChanged.connect(self._on_af_changed)
        row3.addWidget(self._chk_af)
        self._cmb_exp = MComboBox()
        for k, v in sorted(EXPOSURE_OPTIONS.items()):
            self._cmb_exp.addItem(v, k)
        self._cmb_exp.setCurrentText("+0.0 EV")
        self._cmb_exp.currentIndexChanged.connect(self._on_exp_changed)
        row3.addWidget(MLabel("曝光:"))
        row3.addWidget(self._cmb_exp)
        row3.addStretch()
        ctl.addLayout(row3)

        row4 = QHBoxLayout()
        self._cmb_flicker = MComboBox()
        self._cmb_flicker.addItem("60Hz", 0)
        self._cmb_flicker.addItem("50Hz", 1)
        self._cmb_flicker.currentIndexChanged.connect(self._on_flicker_changed)
        row4.addWidget(MLabel("抗频闪:"))
        row4.addWidget(self._cmb_flicker)
        self._cmb_wdr = MComboBox()
        for k, v in WDR_OPTIONS.items():
            self._cmb_wdr.addItem(v, k)
        self._cmb_wdr.currentIndexChanged.connect(self._on_wdr_changed)
        row4.addWidget(MLabel("HDR:"))
        row4.addWidget(self._cmb_wdr)
        row4.addStretch()
        ctl.addLayout(row4)

        self._ctl_section = MSectionItem(
            "摄像头控制", widget=ctl_container, expand=False
        )
        layout.addWidget(self._ctl_section)

    def _on_start(self):
        if self._thread is not None:
            return
        # 1. SDK 初始化 + 应用全部设置（必须在采集前完成）
        try:
            ctl = TinySeCameraControl(0)
            if ctl.init():
                ctl.set_fov(int(self._cmb_fov.currentData() or 0))
                ctl.set_auto_focus(self._chk_af.isChecked())
                ctl.set_exposure_compensation(int(self._cmb_exp.currentData() or 0))
                ctl.set_anti_flicker(int(self._cmb_flicker.currentData() or 0))
                ctl.set_wdr(int(self._cmb_wdr.currentData() or 0))
                ai_sub = int(self._cmb_ai.currentData() or 0)
                ctl.set_ai_mode(ai_sub)
            self._control = ctl
        except Exception as exc:
            QMessageBox.warning(self, "SDK 控制不可用", str(exc))
            self._control = None
        # 2. 启动采集
        self._thread = QThread(self)
        self._capture = TinySeCameraCapture()
        self._capture.moveToThread(self._thread)
        self._thread.started.connect(self._capture.start)
        self._capture.frame_ready.connect(self._on_frame)
        self._capture.stats_updated.connect(self._on_stats)
        self._capture.recording_finished.connect(self._on_recording_finished)
        self._capture.error.connect(self._on_error)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()
        self._set_running(True)

    def _on_stop(self):
        capture = self._capture
        thread = self._thread
        if capture is not None:
            if capture.is_recording:
                capture.stop_record()
            capture.stop()
        if thread is not None:
            thread.quit()
            thread.wait(2000)
        self._thread = None
        self._capture = None
        ctl = self._control
        self._control = None
        if ctl is not None:
            ctl.close()
        self._set_running(False)

    def _on_record(self):
        capture = self._capture
        if capture is None:
            return
        if not capture.is_recording:
            path = capture.start_record()
            if path:
                self._record_path = path
                self._btn_record.setText("Stop Recording")
        else:
            capture.stop_record()

    def _on_frame(self, frame: np.ndarray):
        preview = cv2.resize(frame, (PREVIEW_WIDTH, PREVIEW_HEIGHT), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        image = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        self._preview.setPixmap(QPixmap.fromImage(image))

    def _on_stats(self, fps: float, record_sec: float):
        rec = f" recording {record_sec:.1f}s" if record_sec > 0 else ""
        self._stats.setText(f"Capture {fps:.2f} fps{rec}")

    def _on_recording_finished(self, path: str):
        self._record_path = None
        self._btn_record.setText("Record")
        QMessageBox.information(self, "Recording Finished", path)

    def _on_error(self, message: str):
        QMessageBox.critical(self, "Tiny SE Error", message)
        self._on_stop()

    # ── 控制面板事件（即时发送；采集运行中可能被驱动拒绝，重启预览保证生效）──

    def _ctl(self):
        return self._control

    def _on_mirror(self, _state: int):
        cap = self._capture
        if cap is not None:
            cap.set_mirror(self._chk_mirror.isChecked())

    def _on_fov_changed(self, _idx: int):
        ctl = self._ctl()
        if ctl is not None:
            data = self._cmb_fov.currentData()
            if data is not None:
                ctl.set_fov(int(data))

    def _on_ai_go(self):
        ctl = self._ctl()
        if ctl is not None:
            data = self._cmb_ai.currentData()
            if data is not None:
                ctl.set_ai_mode(int(data))

    def _on_ai_off(self):
        ctl = self._ctl()
        if ctl is not None:
            ctl.set_ai_off()

    def _on_af_changed(self, _state: int):
        ctl = self._ctl()
        if ctl is not None:
            ctl.set_auto_focus(self._chk_af.isChecked())

    def _on_exp_changed(self, _idx: int):
        ctl = self._ctl()
        if ctl is not None:
            data = self._cmb_exp.currentData()
            if data is not None:
                ctl.set_exposure_compensation(int(data))

    def _on_flicker_changed(self, _idx: int):
        ctl = self._ctl()
        if ctl is not None:
            data = self._cmb_flicker.currentData()
            if data is not None:
                ctl.set_anti_flicker(int(data))

    def _on_wdr_changed(self, _idx: int):
        ctl = self._ctl()
        if ctl is not None:
            data = self._cmb_wdr.currentData()
            if data is not None:
                ctl.set_wdr(int(data))

    def _set_running(self, running: bool):
        self._btn_start.setEnabled(not running)
        self._btn_stop.setEnabled(running)
        self._btn_record.setEnabled(running)
        # 控制面板在采集期间保持可用；DShow 运行时部分命令可能被驱动拒绝，
        # 但用户可随时尝试。需重启预览才能保证全部生效。
        if not running:
            self._btn_record.setText("Record")
            self._stats.setText("Idle")

    def closeEvent(self, event):
        self._on_stop()
        super().closeEvent(event)


if __name__ == "__main__":
    with application() as app:
        widget = TinySeCameraWidget()
        dayu_theme.apply(widget)
        widget.show()
        sys.exit(app.exec_())
