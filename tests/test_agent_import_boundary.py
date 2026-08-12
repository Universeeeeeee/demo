"""Import boundary tests for keeping the UI process free of LLM facades."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class AgentImportBoundaryTest(unittest.TestCase):
    def _import_agent_with_disabled_plugins(self, value: str | None) -> str:
        env = os.environ.copy()
        if value is None:
            env.pop("PYDANTIC_DISABLE_PLUGINS", None)
        else:
            env["PYDANTIC_DISABLE_PLUGINS"] = value

        code = (
            "import os, sys;"
            f"sys.path.insert(0, {str(ROOT)!r});"
            "import agent;"
            "print(os.environ['PYDANTIC_DISABLE_PLUGINS'])"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        return result.stdout.strip()

    def test_agent_package_disables_logfire_pydantic_plugin(self):
        self.assertEqual(
            self._import_agent_with_disabled_plugins(None),
            "logfire-plugin",
        )

    def test_agent_package_preserves_other_disabled_plugins(self):
        self.assertEqual(
            self._import_agent_with_disabled_plugins("custom-plugin"),
            "custom-plugin,logfire-plugin",
        )

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

    def test_agent_config_panel_does_not_import_config_runtime_or_report_agent(self):
        code = (
            "import sys;"
            f"sys.path.insert(0, {str(ROOT)!r});"
            "import ui.views.agent_config_panel;"
            "print('|'.join(str(name in sys.modules) for name in ("
            "'agent.config.agent', 'agent.config.service', 'agent.report.agent', "
            "'pydantic_ai')))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), "False|False|False|False")


if __name__ == "__main__":
    unittest.main()
