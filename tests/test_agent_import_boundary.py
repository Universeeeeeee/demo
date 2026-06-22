"""Import boundary tests for keeping the UI process free of LLM facades."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class AgentImportBoundaryTest(unittest.TestCase):
    def test_agent_config_panel_does_not_import_gait_agent_facade(self):
        code = (
            "import sys;"
            f"sys.path.insert(0, {str(ROOT)!r});"
            "import ui.views.agent_config_panel;"
            "print('agent.gait_agent' in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
