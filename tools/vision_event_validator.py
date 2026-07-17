"""Windows sidecar UI for validating visual labels on real grid touch events."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import deque
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


CSV_FIELDS = (
    "event_id",
    "event_time_s",
    "decided_at_s",
    "project_mode",
    "event_role",
    "source_contact_id",
    "source_grid_label",
    "vision_label",
    "candidate_label",
    "confidence",
    "reason",
    "latency_ms",
    "window_frame_count",
    "inference_attempts",
    "pose_total",
    "pose_before",
    "pose_after",
    "max_pose_gap_ms",
    "analysis_fps",
    "pose_fps",
    "sync_status",
    "sync_reason",
    "sync_warmup_ms",
    "sync_offset_ms",
    "sync_uncertainty_ms",
    "sync_sample_period_ms",
    "camera_frame_index",
    "camera_sample_time_s",
    "camera_callback_time_s",
    "camera_legacy_time_s",
    "camera_aligned_time_s",
    "alignment_delta_ms",
    "camera_event_delta_ms",
    "manual_label",
    "is_match",
)


VALIDATOR_VISION_CONFIG = {
    "pre_event_ms": 250,
    "post_event_ms": 200,
    "inference_interval_ms": 60,
    "decision_timeout_ms": 500,
    "min_confidence": 0.65,
    "frame_buffer_ms": 1500,
    "max_frames": 180,
    "max_events": 16,
}


class JumpEventRoleTracker:
    """Distinguish the initial stand-in touch from landings after a lift."""

    def __init__(self) -> None:
        self._seen_touch = False
        self._lift_since_touch = False

    def observe(self, kind: str) -> str | None:
        normalized = kind.lower()
        if normalized == "lift":
            self._lift_since_touch = True
            return None
        if normalized != "touch":
            return None
        if self._lift_since_touch:
            role = "landing"
        elif not self._seen_touch:
            role = "baseline"
        else:
            role = "unpaired_touch"
        self._seen_touch = True
        self._lift_since_touch = False
        return role


def validation_metrics(rows) -> dict[str, float | int]:
    eligible = [
        row
        for row in rows
        if row.get("event_role", "grid_touch") in ("grid_touch", "landing")
    ]
    reviewed = [
        row
        for row in eligible
        if row.get("manual_label") in ("left", "right", "both")
    ]
    covered = sum(row.get("vision_label") != "unknown" for row in eligible)
    return {
        "eligible": len(eligible),
        "reviewed": len(reviewed),
        "correct": sum(row.get("is_match") == "1" for row in reviewed),
        "wrong": sum(row.get("is_match") == "0" for row in reviewed),
        "coverage_percent": covered / len(eligible) * 100.0 if eligible else 0.0,
    }


def event_sync_rejection_reason(status: str) -> str | None:
    if status in ("ready", "unsupported"):
        return None
    if status == "degraded":
        return "clock_sync_degraded"
    return "clock_sync_unavailable"


def _stream_fps(timestamps, *, now_s: float | None = None) -> float:
    if len(timestamps) < 2:
        return 0.0
    if now_s is not None and now_s - timestamps[-1] > 1.0:
        return 0.0
    elapsed = timestamps[-1] - timestamps[0]
    return (len(timestamps) - 1) / elapsed if elapsed > 0 else 0.0


def _csv_float(value, digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"


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
    from vision import (
        CameraClockSynchronizer,
        ClockSyncStatus,
        FootLabel,
        FootVisionService,
        VisionConfig,
    )
    from vision.foot_reference import classify_landing_event, unknown_decision
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
            self._last_frame_timing = None
            self._analysis_times = deque(maxlen=180)
            self._pose_samples = deque(maxlen=64)
            self._pose_ready_times = deque(maxlen=64)
            self._event_frames = {}
            self._event_meta = {}
            self._rows = {}
            self._row_order = []
            self._shortcuts = []
            self._jump_roles = JumpEventRoleTracker()
            self._grid_session_started = False
            self._clock_sync = (
                CameraClockSynchronizer() if args.camera == "tinyse" else None
            )
            self._sync_snapshot = (
                self._clock_sync.snapshot if self._clock_sync is not None else None
            )
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
                "U 无法判断    Q 退出；Jump 首次站入标记为 baseline"
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
                VisionConfig(**VALIDATOR_VISION_CONFIG),
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
                if args.camera != "tinyse":
                    self._start_grid_session()
            except Exception as exc:
                self._device.setText(f"启动失败：{exc}")

        def _start_grid_session(self) -> None:
            if self._grid_session_started:
                return
            self._controller.prepare(build_session_config(args))
            self._controller.start()
            self._grid_session_started = True
            self._device.setText("光栅会话已启动；请先保持检测区空闲 1–2 秒")

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
            if args.camera == "tinyse":
                capture.analysis_frame_timed_ready.connect(
                    self._on_timed_analysis_frame
                )
            else:
                capture.analysis_frame_ready.connect(self._on_analysis_frame)
            capture.stats_updated.connect(self._on_camera_stats)
            capture.error.connect(self._on_camera_error)
            thread.started.connect(capture.start)
            thread.finished.connect(capture.deleteLater)
            self._capture = capture
            self._camera_thread = thread
            thread.start()

        @Slot(object, object)
        def _on_timed_analysis_frame(self, frame, timing) -> None:
            synchronizer = self._clock_sync
            if synchronizer is None:
                return
            snapshot = synchronizer.observe(
                timing.sample_time_s,
                timing.callback_time_s,
                frame_index=timing.frame_index,
            )
            self._sync_snapshot = snapshot
            aligned_time_s = snapshot.aligned_time_s
            frame_timing = {
                "frame_index": timing.frame_index,
                "sample_time_s": timing.sample_time_s,
                "callback_time_s": timing.callback_time_s,
                "legacy_time_s": timing.decoded_at_s,
                "aligned_time_s": aligned_time_s,
                "alignment_delta_ms": (
                    (timing.decoded_at_s - aligned_time_s) * 1000.0
                    if aligned_time_s is not None
                    else None
                ),
            }
            self._last_frame_timing = frame_timing
            if snapshot.status is ClockSyncStatus.READY and aligned_time_s is not None:
                self._analysis_times.append(aligned_time_s)
                self._service.submit_frame(frame, aligned_time_s)
                self._render_analysis_frame(frame, aligned_time_s)
                if not self._grid_session_started:
                    try:
                        self._start_grid_session()
                    except Exception as exc:
                        self._device.setText(f"光栅启动失败：{exc}")
                return

            self._last_frame = frame
            annotated = draw_pose_overlay(frame.copy(), None)
            self._set_preview(self._live_preview, annotated)
            if snapshot.status is ClockSyncStatus.WARMING_UP:
                self._device.setText(
                    "TinySE 时间同步中："
                    f"{synchronizer.sample_count}/30；请保持光栅检测区空闲"
                )
            else:
                self._device.setText(
                    f"TinySE 时间同步失效：{snapshot.reason}；视觉事件将拒识"
                )

        @Slot(object, float)
        def _on_analysis_frame(self, frame, captured_at_s: float) -> None:
            self._last_frame_timing = {
                "frame_index": None,
                "sample_time_s": None,
                "callback_time_s": None,
                "legacy_time_s": captured_at_s,
                "aligned_time_s": captured_at_s,
                "alignment_delta_ms": 0.0,
            }
            self._analysis_times.append(captured_at_s)
            self._service.submit_frame(frame, captured_at_s)
            self._render_analysis_frame(frame, captured_at_s)

        def _render_analysis_frame(self, frame, captured_at_s: float) -> None:
            self._last_frame = frame
            pose = self._nearest_pose(captured_at_s, max_delta_s=0.30)
            annotated = draw_pose_overlay(frame.copy(), pose)
            self._set_preview(self._live_preview, annotated)

        @Slot(object)
        def _on_pose_sample(self, sample) -> None:
            self._pose_samples.append(sample)
            self._pose_ready_times.append(time.perf_counter())

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
                event_role="grid_touch",
            )

        @Slot(object)
        def _on_hop_event(self, ev) -> None:
            event_role = self._jump_roles.observe(ev.kind)
            if event_role is None:
                return
            self._submit_project_touch(
                ev.time,
                source_contact_id="",
                source_grid_label="",
                event_role=event_role,
            )

        def _submit_project_touch(
            self,
            relative_time_s: float,
            *,
            source_contact_id,
            source_grid_label: str,
            event_role: str,
        ) -> None:
            start_time = self._controller.start_time
            if start_time is None:
                return
            self._event_id += 1
            event_id = self._event_id
            event_time_s = absolute_event_time(start_time, relative_time_s)
            snapshot = self._sync_snapshot
            sync_status = (
                snapshot.status.value if snapshot is not None else "unsupported"
            )
            timing = self._last_frame_timing or {}
            self._event_meta[event_id] = {
                "event_time_s": event_time_s,
                "event_role": event_role,
                "source_contact_id": source_contact_id,
                "source_grid_label": source_grid_label,
                "sync_status": sync_status,
                "sync_reason": (
                    snapshot.reason if snapshot is not None else "unsupported"
                ),
                "sync_warmup_ms": (
                    snapshot.warmup_ms if snapshot is not None else None
                ),
                "sync_offset_ms": (
                    snapshot.offset_ms if snapshot is not None else None
                ),
                "sync_uncertainty_ms": (
                    snapshot.uncertainty_ms if snapshot is not None else None
                ),
                "sync_sample_period_ms": (
                    snapshot.sample_period_ms if snapshot is not None else None
                ),
                "camera_frame_index": timing.get("frame_index"),
                "camera_sample_time_s": timing.get("sample_time_s"),
                "camera_callback_time_s": timing.get("callback_time_s"),
                "camera_legacy_time_s": timing.get("legacy_time_s"),
                "camera_aligned_time_s": timing.get("aligned_time_s"),
                "alignment_delta_ms": timing.get("alignment_delta_ms"),
                "camera_event_delta_ms": (
                    (timing["aligned_time_s"] - event_time_s) * 1000.0
                    if timing.get("aligned_time_s") is not None
                    else None
                ),
            }
            if self._last_frame is not None:
                frame_time_s = timing.get("aligned_time_s")
                if frame_time_s is None:
                    frame_time_s = event_time_s
                self._event_frames[event_id] = (
                    self._small_snapshot(self._last_frame),
                    frame_time_s,
                )
                while len(self._event_frames) > 16:
                    self._event_frames.pop(next(iter(self._event_frames)))
            self._result.setText(
                f"光栅触地事件 {event_id}：等待事件后视觉窗口……"
            )
            rejection_reason = (
                event_sync_rejection_reason(sync_status)
                if args.camera == "tinyse"
                else None
            )

            if rejection_reason is not None:
                self._on_decision(
                    unknown_decision(
                        event_id,
                        event_time_s,
                        rejection_reason,
                        decided_at_s=time.perf_counter(),
                    )
                )
            else:
                self._service.submit_touch_event(event_id, event_time_s)

        @Slot(object)
        def _on_decision(self, decision) -> None:
            meta = dict(self._event_meta.get(decision.event_id, {}))
            current_sync = self._sync_snapshot
            if (
                args.camera == "tinyse"
                and current_sync is not None
                and current_sync.status is ClockSyncStatus.DEGRADED
            ):
                decision = replace(
                    decision,
                    label=FootLabel.UNKNOWN,
                    confidence=0.0,
                    reason="clock_sync_degraded",
                    candidate_label=None,
                )
                meta["sync_status"] = "degraded"
                meta["sync_reason"] = current_sync.reason
                meta["sync_uncertainty_ms"] = current_sync.uncertainty_ms
            self._event_meta[decision.event_id] = meta

            decided_at_s = decision.decided_at_s or time.perf_counter()
            latency_ms = (decided_at_s - decision.event_time_s) * 1000.0
            candidate = decision.candidate_label
            previous = self._rows.get(decision.event_id, {})
            diagnostics = decision.diagnostics
            analysis_fps = _stream_fps(
                self._analysis_times,
                now_s=decided_at_s,
            )
            pose_fps = _stream_fps(self._pose_ready_times, now_s=decided_at_s)
            row = {
                "event_id": decision.event_id,
                "event_time_s": f"{decision.event_time_s:.9f}",
                "decided_at_s": f"{decided_at_s:.9f}",
                "project_mode": args.mode,
                "event_role": meta.get("event_role", "grid_touch"),
                "source_contact_id": meta.get("source_contact_id", ""),
                "source_grid_label": meta.get("source_grid_label", ""),
                "vision_label": decision.label.value,
                "candidate_label": candidate.value if candidate is not None else "",
                "confidence": f"{decision.confidence:.6f}",
                "reason": decision.reason,
                "latency_ms": f"{latency_ms:.3f}",
                "window_frame_count": (
                    diagnostics.frame_count if diagnostics is not None else ""
                ),
                "inference_attempts": (
                    diagnostics.inference_attempts if diagnostics is not None else ""
                ),
                "pose_total": (
                    diagnostics.pose_total if diagnostics is not None else ""
                ),
                "pose_before": (
                    diagnostics.pose_before if diagnostics is not None else ""
                ),
                "pose_after": (
                    diagnostics.pose_after if diagnostics is not None else ""
                ),
                "max_pose_gap_ms": _csv_float(
                    diagnostics.max_pose_gap_ms if diagnostics is not None else None
                ),
                "analysis_fps": _csv_float(analysis_fps),
                "pose_fps": _csv_float(pose_fps),
                "sync_status": meta.get("sync_status", ""),
                "sync_reason": meta.get("sync_reason", ""),
                "sync_warmup_ms": _csv_float(meta.get("sync_warmup_ms")),
                "sync_offset_ms": _csv_float(meta.get("sync_offset_ms")),
                "sync_uncertainty_ms": _csv_float(
                    meta.get("sync_uncertainty_ms")
                ),
                "sync_sample_period_ms": _csv_float(
                    meta.get("sync_sample_period_ms")
                ),
                "camera_frame_index": (
                    meta.get("camera_frame_index")
                    if meta.get("camera_frame_index") is not None
                    else ""
                ),
                "camera_sample_time_s": _csv_float(
                    meta.get("camera_sample_time_s"),
                    9,
                ),
                "camera_callback_time_s": _csv_float(
                    meta.get("camera_callback_time_s"),
                    9,
                ),
                "camera_legacy_time_s": _csv_float(
                    meta.get("camera_legacy_time_s"),
                    9,
                ),
                "camera_aligned_time_s": _csv_float(
                    meta.get("camera_aligned_time_s"),
                    9,
                ),
                "alignment_delta_ms": _csv_float(
                    meta.get("alignment_delta_ms")
                ),
                "camera_event_delta_ms": _csv_float(
                    meta.get("camera_event_delta_ms")
                ),
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
            if diagnostics is None:
                diagnostic_text = ""
            else:
                max_gap = _csv_float(diagnostics.max_pose_gap_ms) or "N/A"
                diagnostic_text = (
                    f" | frames={diagnostics.frame_count} "
                    f"attempts={diagnostics.inference_attempts} "
                    f"pose={diagnostics.pose_total} "
                    f"before/after={diagnostics.pose_before}/{diagnostics.pose_after} "
                    f"max_gap={max_gap}ms"
                )
            sync_diagnostics = (
                f"sync={meta.get('sync_status', '')} "
                f"detail={meta.get('sync_reason', '')} "
                f"offset={_csv_float(meta.get('sync_offset_ms')) or 'N/A'}ms "
                "uncertainty="
                f"{_csv_float(meta.get('sync_uncertainty_ms')) or 'N/A'}ms "
                f"period={_csv_float(meta.get('sync_sample_period_ms')) or 'N/A'}ms "
                "legacy-aligned="
                f"{_csv_float(meta.get('alignment_delta_ms')) or 'N/A'}ms"
            )
            self._reason.setText(
                f"原因：{decision.reason}{diagnostic_text}\n{sync_diagnostics}"
            )
            self._show_event_snapshot(decision)
            self._refresh_metrics()

        def _show_event_snapshot(self, decision) -> None:
            snapshot = self._event_frames.pop(decision.event_id, None)
            if snapshot is None:
                return
            frame, frame_time_s = snapshot
            pose = self._nearest_pose(frame_time_s, max_delta_s=0.20)
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
            metrics = validation_metrics(self._rows.values())
            self._metrics.setText(
                f"有效事件 {metrics['eligible']} | 已标注 {metrics['reviewed']} | "
                f"正确 {metrics['correct']} | 错误 {metrics['wrong']} | "
                f"视觉覆盖率 {metrics['coverage_percent']:.1f}%"
            )

        @Slot()
        def _refresh_queue(self) -> None:
            depth = self._service.queue_depth
            now_s = time.perf_counter()
            analysis_fps = _stream_fps(self._analysis_times, now_s=now_s)
            pose_fps = _stream_fps(self._pose_ready_times, now_s=now_s)
            snapshot = self._sync_snapshot
            sync_status = (
                snapshot.status.value if snapshot is not None else "unsupported"
            )
            uncertainty = (
                _csv_float(snapshot.uncertainty_ms)
                if snapshot is not None
                else ""
            )
            sync_text = sync_status
            if uncertainty:
                sync_text += f" uncertainty={uncertainty}ms"
            self._queue.setText(
                f"队列：frames={depth['frames']} events={depth['events']} | "
                f"分析={analysis_fps:.1f} FPS Pose={pose_fps:.1f} FPS | "
                f"sync={sync_text}"
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
            now_s = time.perf_counter()
            analysis_fps = _stream_fps(self._analysis_times, now_s=now_s)
            pose_fps = _stream_fps(self._pose_ready_times, now_s=now_s)
            self.setWindowTitle(
                "Iron_Jump 光栅触地 × 视觉落地脚验证 — "
                f"{args.mode} — {args.camera} — capture {fps:.1f} / "
                f"analysis {analysis_fps:.1f} / pose {pose_fps:.1f} FPS"
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
