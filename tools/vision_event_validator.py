"""Windows sidecar UI for validating visual labels on real grid touch events."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import deque
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


CSV_FIELDS = (
    "event_id",
    "event_time_s",
    "decided_at_s",
    "project_mode",
    "source_contact_id",
    "source_grid_label",
    "vision_label",
    "candidate_label",
    "confidence",
    "reason",
    "latency_ms",
    "manual_label",
    "is_match",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate MediaPipe landing-foot labels on real grid touch events."
    )
    parser.add_argument("--camera", choices=("tinyse", "logi"), default="tinyse")
    parser.add_argument("--model", required=True, help="Path to Pose Landmarker Full .task")
    parser.add_argument(
        "--output",
        default="vision-event-validation.csv",
        help="Validation CSV path",
    )
    parser.add_argument(
        "--mode",
        choices=("treadmill-gait", "treadmill-running", "jump"),
        default="treadmill-gait",
    )
    parser.add_argument("--speed", type=_positive_float, default=1.0)
    parser.add_argument(
        "--direction",
        choices=("Interface side", "Opposite side"),
        default="Interface side",
    )
    parser.add_argument("--starting-foot", choices=("left", "right"))
    return parser


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("speed must be positive")
    return parsed


def absolute_event_time(session_start_s: float, relative_event_s: float) -> float:
    return session_start_s + relative_event_s


def build_session_config(args: argparse.Namespace):
    if args.mode == "jump":
        from config.test_config import TestConfig

        return TestConfig(
            test_type="Jump Test",
            stop_type="Software command",
            number_of_jumps=None,
        )

    from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig

    common = {
        "stop_type": "Software command",
        "test_length": None,
        "treadmill_speed": args.speed,
        "direction": args.direction,
        "starting_foot_override": args.starting_foot,
    }
    if args.mode == "treadmill-running":
        return TreadmillRunningConfig(**common)
    return TreadmillGaitConfig(**common)


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
        QVBoxLayout,
        QWidget,
    )

    from camera.logi_camera import CAMERA_INDEX, CameraCapture
    from camera.tinyse_camera import TinySeCameraCapture
    from ui.session_controller import SessionController
    from vision import FootVisionService, VisionConfig
    from vision.foot_reference import classify_landing_event
    from vision.pose_overlay import draw_pose_overlay

    class _Bridge(QObject):
        decision = Signal(object)
        pose = Signal(object)
        status = Signal(str)

    class ValidationWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Iron_Jump 光栅触地 × 视觉落地脚验证")
            self.resize(1500, 860)
            self._closing = False
            self._event_id = 0
            self._current_event_id = None
            self._capture = None
            self._camera_thread = None
            self._last_frame = None
            self._pose_samples = deque(maxlen=64)
            self._event_frames = {}
            self._event_meta = {}
            self._rows = {}
            self._row_order = []
            self._shortcuts = []
            self._output_path = Path(args.output).expanduser().resolve()
            self._output_path.parent.mkdir(parents=True, exist_ok=True)

            self._live_preview = QLabel("正在连接相机……")
            self._live_preview.setAlignment(Qt.AlignCenter)
            self._live_preview.setMinimumSize(900, 540)
            self._live_preview.setStyleSheet("background:#111; color:#aaa;")
            self._event_preview = QLabel("等待真实光栅触地事件")
            self._event_preview.setAlignment(Qt.AlignCenter)
            self._event_preview.setMinimumSize(480, 300)
            self._event_preview.setStyleSheet("background:#181818; color:#aaa;")

            previews = QHBoxLayout()
            previews.addWidget(self._live_preview, 2)
            previews.addWidget(self._event_preview, 1)

            self._result = QLabel("等待光栅 touch……")
            self._result.setStyleSheet("font-size:20px; font-weight:700;")
            self._reason = QLabel("视觉模型正在初始化……")
            self._device = QLabel("光栅会话正在初始化……")
            self._queue = QLabel("队列：frames=0 events=0")
            self._metrics = QLabel("已标注 0 | 正确 0 | 错误 0 | 视觉覆盖率 0.0%")
            self._help = QLabel(
                "真实 touch 到来后自动判断落地脚；右侧保留事件画面。\n"
                "启动时先保持光栅无接触；L 左脚 / R 右脚 / B 双脚 / "
                "U 无法判断    Q 退出"
            )

            layout = QVBoxLayout(self)
            layout.addLayout(previews, 1)
            layout.addWidget(self._result)
            layout.addWidget(self._reason)
            layout.addWidget(self._device)
            layout.addWidget(self._queue)
            layout.addWidget(self._metrics)
            layout.addWidget(self._help)

            self._install_shortcut("Q", self.close)
            self._install_shortcut("L", lambda: self._annotate("left"))
            self._install_shortcut("R", lambda: self._annotate("right"))
            self._install_shortcut("B", lambda: self._annotate("both"))
            self._install_shortcut("U", lambda: self._annotate("unknown"))

            self._bridge = _Bridge(self)
            self._bridge.decision.connect(self._on_decision)
            self._bridge.pose.connect(self._on_pose_sample)
            self._bridge.status.connect(self._on_vision_status)

            self._service = FootVisionService(
                VisionConfig(
                    pre_event_ms=180,
                    post_event_ms=120,
                    inference_interval_ms=60,
                    decision_timeout_ms=500,
                    min_confidence=0.65,
                    frame_buffer_ms=1500,
                    max_frames=180,
                    max_events=16,
                ),
                Path(args.model).expanduser(),
                classifier=classify_landing_event,
            )
            self._service.decision_ready.connect(self._bridge.decision.emit)
            self._service.pose_ready.connect(self._bridge.pose.emit)
            self._service.status_changed.connect(self._bridge.status.emit)
            self._service.start()

            self._controller = SessionController(self)
            self._controller.gait_step_event.connect(self._on_gait_step_event)
            self._controller.hop_event.connect(self._on_hop_event)
            self._controller.device_message.connect(self._on_device_message)
            self._controller.session_finished.connect(self._on_session_finished)

            self._queue_timer = QTimer(self)
            self._queue_timer.timeout.connect(self._refresh_queue)
            self._queue_timer.start(100)

            self._write_csv()
            try:
                self._start_camera()
                self._controller.prepare(build_session_config(args))
                self._controller.start()
            except Exception as exc:
                self._device.setText(f"启动失败：{exc}")

        def _install_shortcut(self, key: str, callback) -> None:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

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
            capture.analysis_frame_ready.connect(self._on_analysis_frame)
            capture.stats_updated.connect(self._on_camera_stats)
            capture.error.connect(self._on_camera_error)
            thread.started.connect(capture.start)
            thread.finished.connect(capture.deleteLater)
            self._capture = capture
            self._camera_thread = thread
            thread.start()

        @Slot(object, float)
        def _on_analysis_frame(self, frame, captured_at_s: float) -> None:
            self._last_frame = frame
            pose = self._nearest_pose(captured_at_s, max_delta_s=0.30)
            annotated = draw_pose_overlay(frame.copy(), pose)
            self._set_preview(self._live_preview, annotated)

        @Slot(object)
        def _on_pose_sample(self, sample) -> None:
            self._pose_samples.append(sample)

        @Slot(object)
        def _on_gait_step_event(self, ev) -> None:
            if ev.kind != "touch":
                return
            relative_time = ev.contact.touch_time
            if relative_time is None:
                return
            self._submit_project_touch(
                relative_time,
                source_contact_id=ev.contact.contact_id,
                source_grid_label=ev.contact.foot_label or "",
            )

        @Slot(object)
        def _on_hop_event(self, ev) -> None:
            if ev.kind != "touch":
                return
            self._submit_project_touch(
                ev.time,
                source_contact_id="",
                source_grid_label="",
            )

        def _submit_project_touch(
            self,
            relative_time_s: float,
            *,
            source_contact_id,
            source_grid_label: str,
        ) -> None:
            start_time = self._controller.start_time
            if start_time is None:
                return
            self._event_id += 1
            event_id = self._event_id
            event_time_s = absolute_event_time(start_time, relative_time_s)
            self._event_meta[event_id] = {
                "event_time_s": event_time_s,
                "source_contact_id": source_contact_id,
                "source_grid_label": source_grid_label,
            }
            if self._last_frame is not None:
                self._event_frames[event_id] = self._small_snapshot(self._last_frame)
                while len(self._event_frames) > 16:
                    self._event_frames.pop(next(iter(self._event_frames)))
            self._result.setText(
                f"光栅触地事件 {event_id}：等待事件后视觉窗口……"
            )
            self._service.submit_touch_event(event_id, event_time_s)

        @Slot(object)
        def _on_decision(self, decision) -> None:
            decided_at_s = decision.decided_at_s or time.perf_counter()
            latency_ms = (decided_at_s - decision.event_time_s) * 1000.0
            candidate = decision.candidate_label
            meta = self._event_meta.get(decision.event_id, {})
            previous = self._rows.get(decision.event_id, {})
            row = {
                "event_id": decision.event_id,
                "event_time_s": f"{decision.event_time_s:.9f}",
                "decided_at_s": f"{decided_at_s:.9f}",
                "project_mode": args.mode,
                "source_contact_id": meta.get("source_contact_id", ""),
                "source_grid_label": meta.get("source_grid_label", ""),
                "vision_label": decision.label.value,
                "candidate_label": candidate.value if candidate is not None else "",
                "confidence": f"{decision.confidence:.6f}",
                "reason": decision.reason,
                "latency_ms": f"{latency_ms:.3f}",
                "manual_label": previous.get("manual_label", ""),
                "is_match": previous.get("is_match", ""),
            }
            self._rows[decision.event_id] = row
            if decision.event_id not in self._row_order:
                self._row_order.append(decision.event_id)
            self._current_event_id = decision.event_id
            self._write_csv()

            display_label = decision.label.value.upper()
            if decision.label.value == "unknown" and candidate is not None:
                display_label += f"（候选 {candidate.value.upper()}）"
            self._result.setText(
                f"触地事件 {decision.event_id}：{display_label}  "
                f"置信度 {decision.confidence:.3f}  延迟 {latency_ms:.1f} ms"
            )
            self._reason.setText(f"原因：{decision.reason}")
            self._show_event_snapshot(decision)
            self._refresh_metrics()

        def _show_event_snapshot(self, decision) -> None:
            frame = self._event_frames.pop(decision.event_id, None)
            if frame is None:
                return
            pose = self._nearest_pose(decision.event_time_s, max_delta_s=0.20)
            annotated = draw_pose_overlay(frame.copy(), pose)
            cv2.putText(
                annotated,
                f"EVENT {decision.event_id}: {decision.label.value.upper()} "
                f"{decision.confidence:.2f}",
                (16, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            self._set_preview(self._event_preview, annotated)

        def _annotate(self, label: str) -> None:
            event_id = self._current_event_id
            if event_id is None or event_id not in self._rows:
                return
            row = self._rows[event_id]
            row["manual_label"] = label
            if label == "unknown":
                row["is_match"] = ""
            else:
                row["is_match"] = "1" if row["vision_label"] == label else "0"
            self._write_csv()
            self._refresh_metrics()

        def _nearest_pose(self, timestamp_s: float, *, max_delta_s: float):
            if not self._pose_samples:
                return None
            sample = min(
                self._pose_samples,
                key=lambda item: abs(item.timestamp_s - timestamp_s),
            )
            if abs(sample.timestamp_s - timestamp_s) > max_delta_s:
                return None
            return sample

        @staticmethod
        def _small_snapshot(frame):
            height, width = frame.shape[:2]
            scale = min(1.0, 640.0 / width)
            if scale == 1.0:
                return frame.copy()
            return cv2.resize(
                frame,
                (round(width * scale), round(height * scale)),
                interpolation=cv2.INTER_AREA,
            )

        @staticmethod
        def _set_preview(label, frame) -> None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width = rgb.shape[:2]
            target = label.size()
            scale = min(target.width() / width, target.height() / height)
            display_size = (
                max(1, round(width * scale)),
                max(1, round(height * scale)),
            )
            if display_size != (width, height):
                rgb = cv2.resize(rgb, display_size, interpolation=cv2.INTER_AREA)
            image = QImage(
                rgb.data,
                rgb.shape[1],
                rgb.shape[0],
                rgb.strides[0],
                QImage.Format_RGB888,
            ).copy()
            label.setPixmap(QPixmap.fromImage(image))

        def _write_csv(self) -> None:
            with self._output_path.open("w", newline="", encoding="utf-8-sig") as file:
                writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
                writer.writeheader()
                for event_id in self._row_order:
                    writer.writerow(self._rows[event_id])

        def _refresh_metrics(self) -> None:
            rows = list(self._rows.values())
            reviewed = [
                row for row in rows if row["manual_label"] in ("left", "right", "both")
            ]
            correct = sum(row["is_match"] == "1" for row in reviewed)
            wrong = sum(row["is_match"] == "0" for row in reviewed)
            covered = sum(row["vision_label"] != "unknown" for row in rows)
            coverage = covered / len(rows) * 100.0 if rows else 0.0
            self._metrics.setText(
                f"已标注 {len(reviewed)} | 正确 {correct} | 错误 {wrong} | "
                f"视觉覆盖率 {coverage:.1f}%"
            )

        @Slot()
        def _refresh_queue(self) -> None:
            depth = self._service.queue_depth
            self._queue.setText(
                f"队列：frames={depth['frames']} events={depth['events']}"
            )

        @Slot(str)
        def _on_vision_status(self, status: str) -> None:
            self._reason.setText(f"视觉服务：{status}")

        @Slot(str)
        def _on_device_message(self, message: str) -> None:
            self._device.setText(f"光栅：{message}")

        @Slot(object)
        def _on_session_finished(self, _report) -> None:
            self._device.setText("光栅会话已结束")

        @Slot(float, float)
        def _on_camera_stats(self, fps: float, _record_seconds: float) -> None:
            self.setWindowTitle(
                "Iron_Jump 光栅触地 × 视觉落地脚验证 — "
                f"{args.mode} — {args.camera} — {fps:.1f} FPS"
            )

        @Slot(str)
        def _on_camera_error(self, message: str) -> None:
            self._device.setText(f"相机错误：{message}")

        def closeEvent(self, event) -> None:
            if self._closing:
                event.accept()
                return
            self._closing = True
            self._queue_timer.stop()
            if self._controller.is_running:
                self._controller.stop()
            capture = self._capture
            thread = self._camera_thread
            if capture is not None:
                capture.stop()
            if thread is not None:
                thread.quit()
                thread.wait(2000)
            self._service.stop()
            event.accept()

    app = QApplication.instance() or QApplication(sys.argv)
    window = ValidationWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
