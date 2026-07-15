import ast
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VISION = ROOT / "vision"


class VisionPackageBoundaryTests(unittest.TestCase):
    def test_public_api_is_small_and_stable(self):
        import vision

        self.assertEqual(
            set(vision.__all__),
            {
                "FootLabel",
                "FootVisionService",
                "VisionConfig",
                "VisionDecision",
                "VisionInferenceError",
                "VisionUnavailableError",
            },
        )

    def test_vision_does_not_import_project_engine_ui_hardware_or_config(self):
        forbidden = {"engine", "ui", "hardware", "config", "camera"}
        matches = []
        for path in VISION.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    roots = {node.module.split(".")[0]}
                else:
                    continue
                if roots & forbidden:
                    matches.append((path.name, node.lineno, roots & forbidden))

        self.assertEqual(matches, [])

    def test_importing_vision_does_not_import_mediapipe(self):
        code = "import sys, vision; print('mediapipe' in sys.modules)"

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
