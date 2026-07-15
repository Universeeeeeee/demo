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

    def test_source_uses_real_project_touch_events_and_timestamped_camera_frames(self):
        source = PATH.read_text(encoding="utf-8")

        self.assertIn("SessionController", source)
        self.assertIn("gait_step_event", source)
        self.assertIn('ev.kind != "touch"', source)
        self.assertIn("analysis_frame_ready", source)
        self.assertNotIn("_event_timer", source)


if __name__ == "__main__":
    unittest.main()
