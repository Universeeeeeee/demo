"""Standalone Windows diagnostic UI for the visual foot-reference service."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


CSV_FIELDS = (
    "event_id",
    "event_time_s",
    "decided_at_s",
    "label",
    "confidence",
    "reason",
    "latency_ms",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test Tiny SE/Logitech camera frames with MediaPipe foot labels."
    )
    parser.add_argument("--camera", choices=("tinyse", "logi"), default="tinyse")
    parser.add_argument("--model", required=True, help="Path to Pose Landmarker Full .task")
    parser.add_argument("--output", default="vision-results.csv", help="CSV result path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


def run(args: argparse.Namespace) -> int:
    import cv2
    from qtpy.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt
    from qtpy.QtGui import QImage, QKeySequence, QPixmap, QShortcut
    from qtpy.QtWidgets import (
        QApplication,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    from camera.logi_camera import CAMERA_INDEX, CameraCapture
    from camera.tinyse_camera import TinySeCameraCapture
    from vision import FootVisionService, VisionConfig

    class _Bridge(QObject):
        decision = Signal(object)
        status = Signal(str)

    class DiagnosticWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Iron_Jump 视觉左右脚诊断")
            self.resize(1100, 760)
            self._event_id = 0
            self._closing = False
            self._capture = None
            self._camera_thread = None

            output_path = Path(args.output).expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._csv_file = output_path.open("w", newline="", encoding="utf-8-sig")
            self._csv = csv.DictWriter(self._csv_file, fieldnames=CSV_FIELDS)
            self._csv.writeheader()
            self._csv_file.flush()

            self._preview = QLabel("正在连接相机……")
            self._preview.setAlignment(Qt.AlignCenter)
            self._preview.setMinimumSize(960, 540)
            self._preview.setStyleSheet("background:#111; color:#aaa;")

            self._result = QLabel("尚未触发事件")
            self._result.setStyleSheet("font-size:18px; font-weight:600;")
            self._status = QLabel("正在初始化视觉模型……")
            self._queue = QLabel("队列：frames=0 events=0")
            self._help = QLabel(
                "空格：模拟一次光栅触地事件    Q：退出\n"
                "注意：这是独立视觉诊断，不代表真实光栅同步已经验证。"
            )

            trigger = QPushButton("模拟触地（Space）")
            trigger.setShortcut(QKeySequence("Space"))
            trigger.clicked.connect(self._submit_event)

            controls = QHBoxLayout()
            controls.addWidget(trigger)
            controls.addWidget(self._result, 1)

            layout = QVBoxLayout(self)
            layout.addWidget(self._preview, 1)
            layout.addLayout(controls)
            layout.addWidget(self._status)
            layout.addWidget(self._queue)
            layout.addWidget(self._help)

            quit_shortcut = QShortcut(QKeySequence("Q"), self)
            quit_shortcut.activated.connect(self.close)
            self._quit_shortcut = quit_shortcut

            self._bridge = _Bridge(self)
            self._bridge.decision.connect(self._on_decision)
            self._bridge.status.connect(self._on_service_status)

            self._service = FootVisionService(
                VisionConfig(),
                Path(args.model).expanduser(),
            )
            self._service.decision_ready.connect(self._bridge.decision.emit)
            self._service.status_changed.connect(self._bridge.status.emit)
            self._service.start()

            self._queue_timer = QTimer(self)
            self._queue_timer.timeout.connect(self._refresh_queue)
            self._queue_timer.start(100)

            try:
                self._start_camera()
            except Exception as exc:
                self._status.setText(f"相机不可用：{exc}")

        def _start_camera(self) -> None:
            if args.camera == "tinyse":
                capture = TinySeCameraCapture()
            else:
                capture = CameraCapture()
                if not capture.open(CAMERA_INDEX):
                    raise RuntimeError("无法打开 Logitech 相机")

            thread = QThread(self)
            capture.moveToThread(thread)
            capture.analysis_frame_ready.connect(self._service.submit_frame)
            capture.frame_ready.connect(self._on_preview_frame)
            capture.stats_updated.connect(self._on_camera_stats)
            capture.error.connect(self._on_camera_error)
            thread.started.connect(capture.start)
            thread.finished.connect(capture.deleteLater)

            self._capture = capture
            self._camera_thread = thread
            thread.start()

        @Slot()
        def _submit_event(self) -> None:
            self._event_id += 1
            event_time_s = time.perf_counter()
            self._result.setText(f"事件 {self._event_id}：等待窗口完成……")
            self._service.submit_touch_event(self._event_id, event_time_s)

        @Slot(object)
        def _on_decision(self, decision) -> None:
            decided_at_s = decision.decided_at_s or time.perf_counter()
            latency_ms = (decided_at_s - decision.event_time_s) * 1000.0
            self._result.setText(
                f"事件 {decision.event_id}：{decision.label.value.upper()}  "
                f"置信度 {decision.confidence:.3f}  延迟 {latency_ms:.1f} ms"
            )
            self._status.setText(f"原因：{decision.reason}")
            self._csv.writerow(
                {
                    "event_id": decision.event_id,
                    "event_time_s": f"{decision.event_time_s:.9f}",
                    "decided_at_s": f"{decided_at_s:.9f}",
                    "label": decision.label.value,
                    "confidence": f"{decision.confidence:.6f}",
                    "reason": decision.reason,
                    "latency_ms": f"{latency_ms:.3f}",
                }
            )
            self._csv_file.flush()

        @Slot(str)
        def _on_service_status(self, status: str) -> None:
            self._status.setText(f"视觉服务：{status}")

        @Slot(float, float)
        def _on_camera_stats(self, fps: float, _record_seconds: float) -> None:
            self.setWindowTitle(
                f"Iron_Jump 视觉左右脚诊断 — {args.camera} — {fps:.1f} FPS"
            )

        @Slot(str)
        def _on_camera_error(self, message: str) -> None:
            self._status.setText(f"相机错误：{message}")

        @Slot(object)
        def _on_preview_frame(self, frame) -> None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width = rgb.shape[:2]
            target = self._preview.size()
            scale = min(target.width() / width, target.height() / height)
            display_width = max(1, int(width * scale))
            display_height = max(1, int(height * scale))
            if (display_width, display_height) != (width, height):
                rgb = cv2.resize(
                    rgb,
                    (display_width, display_height),
                    interpolation=cv2.INTER_AREA,
                )
            image = QImage(
                rgb.data,
                rgb.shape[1],
                rgb.shape[0],
                rgb.strides[0],
                QImage.Format_RGB888,
            ).copy()
            self._preview.setPixmap(QPixmap.fromImage(image))

        @Slot()
        def _refresh_queue(self) -> None:
            depth = self._service.queue_depth
            self._queue.setText(
                f"队列：frames={depth['frames']} events={depth['events']}"
            )

        def closeEvent(self, event) -> None:
            if self._closing:
                event.accept()
                return
            self._closing = True
            self._queue_timer.stop()
            capture = self._capture
            thread = self._camera_thread
            if capture is not None:
                capture.stop()
            if thread is not None:
                thread.quit()
                thread.wait(2000)
            self._service.stop()
            self._csv_file.close()
            event.accept()

    app = QApplication.instance() or QApplication(sys.argv)
    window = DiagnosticWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
