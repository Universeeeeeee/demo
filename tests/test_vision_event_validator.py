import importlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools/vision_event_validator.py"


class VisionEventValidatorContractTests(unittest.TestCase):
    def test_import_is_lazy_and_does_not_load_qt_camera_or_controller(self):
        sys.modules.pop("tools.vision_event_validator", None)
        before = set(sys.modules)

        importlib.import_module("tools.vision_event_validator")

        loaded = set(sys.modules) - before
        self.assertFalse(any(name == "qtpy" or name.startswith("qtpy.") for name in loaded))
        self.assertFalse(any(name.startswith("camera.") for name in loaded))
        self.assertFalse(any(name.startswith("ui.") for name in loaded))

    def test_parser_defaults_to_tinyse_treadmill_gait(self):
        module = importlib.import_module("tools.vision_event_validator")

        args = module.build_parser().parse_args(["--model", "pose.task"])

        self.assertEqual(args.camera, "tinyse")
        self.assertEqual(args.mode, "treadmill-gait")
        self.assertEqual(args.output, "vision-event-validation.csv")

    def test_absolute_event_time_uses_session_monotonic_origin(self):
        module = importlib.import_module("tools.vision_event_validator")

        self.assertAlmostEqual(module.absolute_event_time(100.25, 1.75), 102.0)

    def test_csv_contains_project_vision_and_manual_truth_fields(self):
        module = importlib.import_module("tools.vision_event_validator")

        self.assertIn("source_contact_id", module.CSV_FIELDS)
        self.assertIn("source_grid_label", module.CSV_FIELDS)
        self.assertIn("vision_label", module.CSV_FIELDS)
        self.assertIn("manual_label", module.CSV_FIELDS)
        self.assertIn("is_match", module.CSV_FIELDS)
        self.assertIn("event_role", module.CSV_FIELDS)
        self.assertIn("inference_attempts", module.CSV_FIELDS)
        self.assertIn("pose_total", module.CSV_FIELDS)
        self.assertIn("pose_before", module.CSV_FIELDS)
        self.assertIn("pose_after", module.CSV_FIELDS)
        self.assertIn("max_pose_gap_ms", module.CSV_FIELDS)
        self.assertIn("analysis_fps", module.CSV_FIELDS)
        self.assertIn("pose_fps", module.CSV_FIELDS)
        self.assertIn("sync_status", module.CSV_FIELDS)
        self.assertIn("sync_reason", module.CSV_FIELDS)
        self.assertIn("sync_warmup_ms", module.CSV_FIELDS)
        self.assertIn("sync_offset_ms", module.CSV_FIELDS)
        self.assertIn("sync_uncertainty_ms", module.CSV_FIELDS)
        self.assertIn("sync_sample_period_ms", module.CSV_FIELDS)
        self.assertIn("camera_frame_index", module.CSV_FIELDS)
        self.assertIn("camera_sample_time_s", module.CSV_FIELDS)
        self.assertIn("camera_callback_time_s", module.CSV_FIELDS)
        self.assertIn("camera_legacy_time_s", module.CSV_FIELDS)
        self.assertIn("camera_aligned_time_s", module.CSV_FIELDS)
        self.assertIn("alignment_delta_ms", module.CSV_FIELDS)
        self.assertIn("camera_event_delta_ms", module.CSV_FIELDS)

    def test_validator_window_defaults_prioritize_pose_coverage(self):
        module = importlib.import_module("tools.vision_event_validator")

        self.assertEqual(
            module.VALIDATOR_VISION_CONFIG,
            {
                "pre_event_ms": 250,
                "post_event_ms": 200,
                "inference_interval_ms": 60,
                "decision_timeout_ms": 500,
                "min_confidence": 0.65,
                "frame_buffer_ms": 1500,
                "max_frames": 180,
                "max_events": 16,
            },
        )

    def test_jump_role_tracker_marks_baseline_landing_and_unpaired_touches(self):
        module = importlib.import_module("tools.vision_event_validator")
        tracker = module.JumpEventRoleTracker()

        self.assertEqual(tracker.observe("touch"), "baseline")
        self.assertIsNone(tracker.observe("lift"))
        self.assertEqual(tracker.observe("touch"), "landing")
        self.assertEqual(tracker.observe("touch"), "unpaired_touch")

        tracker = module.JumpEventRoleTracker()
        self.assertIsNone(tracker.observe("lift"))
        self.assertEqual(tracker.observe("touch"), "landing")

    def test_baseline_does_not_enter_coverage_or_accuracy_metrics(self):
        module = importlib.import_module("tools.vision_event_validator")
        rows = [
            {
                "event_role": "baseline",
                "vision_label": "unknown",
                "manual_label": "both",
                "is_match": "0",
            },
            {
                "event_role": "landing",
                "vision_label": "left",
                "manual_label": "left",
                "is_match": "1",
            },
            {
                "event_role": "landing",
                "vision_label": "unknown",
                "manual_label": "",
                "is_match": "",
            },
        ]

        metrics = module.validation_metrics(rows)

        self.assertEqual(metrics["eligible"], 2)
        self.assertEqual(metrics["reviewed"], 1)
        self.assertEqual(metrics["correct"], 1)
        self.assertEqual(metrics["wrong"], 0)
        self.assertEqual(metrics["coverage_percent"], 50.0)

    def test_sync_rejection_is_fail_safe(self):
        module = importlib.import_module("tools.vision_event_validator")

        self.assertIsNone(module.event_sync_rejection_reason("ready"))
        self.assertIsNone(module.event_sync_rejection_reason("unsupported"))
        self.assertEqual(
            module.event_sync_rejection_reason("warming_up"),
            "clock_sync_unavailable",
        )
        self.assertEqual(
            module.event_sync_rejection_reason("degraded"),
            "clock_sync_degraded",
        )

    def test_stream_fps_and_optional_csv_values_are_diagnostic_safe(self):
        module = importlib.import_module("tools.vision_event_validator")

        self.assertEqual(module._stream_fps([]), 0.0)
        self.assertEqual(module._stream_fps([1.0]), 0.0)
        self.assertAlmostEqual(module._stream_fps([1.0, 1.1, 1.2]), 10.0)
        self.assertEqual(module._stream_fps([1.0, 1.1, 1.2], now_s=2.3), 0.0)
        self.assertEqual(module._csv_float(None), "")
        self.assertEqual(module._csv_float(1.23456), "1.235")

    def test_source_gates_grid_start_and_pending_decisions_on_sync_state(self):
        source = PATH.read_text(encoding="utf-8")

        self.assertIn("snapshot.status is ClockSyncStatus.READY", source)
        self.assertIn("if not self._grid_session_started", source)
        self.assertIn("current_sync.status is ClockSyncStatus.DEGRADED", source)
        self.assertIn('reason="clock_sync_degraded"', source)

    def test_source_uses_real_project_touch_events_and_timestamped_camera_frames(self):
        source = PATH.read_text(encoding="utf-8")

        self.assertIn("SessionController", source)
        self.assertIn("gait_step_event", source)
        self.assertIn('ev.kind != "touch"', source)
        self.assertIn("analysis_frame_timed_ready", source)
        self.assertIn("analysis_frame_ready", source)
        self.assertNotIn("_event_timer", source)


if __name__ == "__main__":
    unittest.main()
