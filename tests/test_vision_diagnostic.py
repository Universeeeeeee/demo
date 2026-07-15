import ast
import importlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools/vision_diagnostic.py"


class VisionDiagnosticContractTests(unittest.TestCase):
    def test_parser_accepts_tinyse_model_and_csv_output(self):
        module = importlib.import_module("tools.vision_diagnostic")

        args = module.build_parser().parse_args(
            [
                "--camera",
                "tinyse",
                "--model",
                r"C:\Iron_Jump\models\pose_landmarker_full.task",
                "--output",
                "vision-results.csv",
            ]
        )

        self.assertEqual(args.camera, "tinyse")
        self.assertTrue(args.model.endswith("pose_landmarker_full.task"))
        self.assertEqual(args.output, "vision-results.csv")

    def test_import_does_not_load_qt_or_camera(self):
        sys.modules.pop("tools.vision_diagnostic", None)
        before = set(sys.modules)

        importlib.import_module("tools.vision_diagnostic")

        loaded = set(sys.modules) - before
        self.assertFalse(any(name == "qtpy" or name.startswith("qtpy.") for name in loaded))
        self.assertFalse(any(name.startswith("camera.") for name in loaded))

    def test_source_uses_only_camera_and_vision_project_interfaces(self):
        tree = ast.parse(PATH.read_text(encoding="utf-8"))
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])

        self.assertNotIn("engine", imported_roots)
        self.assertNotIn("ui", imported_roots)
        self.assertNotIn("hardware", imported_roots)
        self.assertNotIn("config", imported_roots)
        self.assertIn("camera", imported_roots)
        self.assertIn("vision", imported_roots)

    def test_csv_schema_contains_timing_label_confidence_and_reason(self):
        module = importlib.import_module("tools.vision_diagnostic")

        self.assertEqual(
            module.CSV_FIELDS,
            (
                "event_id",
                "event_time_s",
                "decided_at_s",
                "label",
                "confidence",
                "reason",
                "latency_ms",
            ),
        )


if __name__ == "__main__":
    unittest.main()
