from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import vision_app


class VisionAppContractTests(unittest.TestCase):
    def test_parser_routes_internal_record_mode(self):
        args = vision_app.build_parser().parse_args(
            [
                "--record",
                "--model",
                "pose.task",
                "--output-root",
                "sessions",
                "--mode",
                "treadmill-running",
                "--starting-foot",
                "right",
            ]
        )
        self.assertTrue(args.record)
        self.assertEqual(args.model, "pose.task")
        self.assertEqual(args.mode, "treadmill-running")
        self.assertEqual(args.starting_foot, "right")

    def test_default_user_data_is_outside_application_directory(self):
        self.assertEqual(
            vision_app.default_output_root(),
            Path.home() / "Documents" / "IronJump" / "vision_sessions",
        )
        self.assertEqual(
            vision_app.default_log_root(),
            Path.home() / "Documents" / "IronJump" / "app_logs",
        )

    def test_remembered_model_precedes_bundled_and_development_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            remembered = root / "remembered.task"
            bundled_root = root / "bundle"
            development_root = root / "source"
            remembered.write_bytes(b"remembered")
            (bundled_root / "models").mkdir(parents=True)
            (development_root / "models").mkdir(parents=True)
            (bundled_root / "models" / vision_app.MODEL_NAME).write_bytes(b"bundle")
            (development_root / "models" / vision_app.MODEL_NAME).write_bytes(b"source")
            with (
                patch.object(vision_app, "resource_root", return_value=bundled_root),
                patch.object(vision_app, "PROJECT_ROOT", development_root),
            ):
                self.assertEqual(
                    vision_app.find_model(str(remembered)), remembered.resolve()
                )
                remembered.unlink()
                self.assertEqual(
                    vision_app.find_model(str(remembered)),
                    (bundled_root / "models" / vision_app.MODEL_NAME).resolve(),
                )

    def test_session_status_rejects_recording_and_accepts_partial_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(vision_app.read_session_status(root), "invalid")
            for status in ("recording", "partial", "complete"):
                (root / "session.json").write_text(
                    json.dumps({"status": status}), encoding="utf-8"
                )
                self.assertEqual(vision_app.read_session_status(root), status)

    def test_development_child_command_reuses_same_entrypoint(self):
        with patch.object(sys, "frozen", False, create=True):
            program, arguments = vision_app._child_command(["--replay", "session"])
        self.assertEqual(program, sys.executable)
        self.assertEqual(Path(arguments[0]).name, "vision_app.py")
        self.assertEqual(arguments[1:], ["--replay", "session"])

    def test_packaging_files_define_windowed_onedir_and_optional_model(self):
        root = Path(__file__).resolve().parents[1]
        spec = (root / "IronJumpVisionTools.spec").read_text(encoding="utf-8")
        batch = (root / "build_vision_app.bat").read_text(encoding="utf-8")
        self.assertIn('name="IronJumpVisionTools"', spec)
        self.assertIn("console=False", spec)
        self.assertIn("if model.is_file()", spec)
        self.assertIn("camera/bin/*.dll", spec)
        self.assertIn("hardware/CyUsbInterface.dll", spec)
        self.assertIn("pip install pyinstaller", batch)
        self.assertIn("IronJumpVisionTools.spec", batch)


if __name__ == "__main__":
    unittest.main()
