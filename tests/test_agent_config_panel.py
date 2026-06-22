"""Regression tests for AgentConfigPanel request lifecycle handling."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qtpy.QtWidgets import QApplication

from ui.views.agent_config_panel import AgentConfigPanel, _LLMHttpWorker


_APP = None


def _app():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
    else:
        _APP = app
    return _APP


class _FakeClient:
    is_running = True

    def start(self):
        return True

    def worker_status(self, timeout=0.25):
        return "ready"

    def chat(self, message, athlete):
        return {"reply": f"reply: {message}"}

    def reset(self):
        pass


class _RestartingClient:
    is_running = True

    def __init__(self):
        self.status_calls = []
        self.chat_calls = []

    def start(self):
        return True

    def worker_status(self, timeout=0.25):
        self.status_calls.append(timeout)
        return "starting"

    def chat(self, message, athlete):
        self.chat_calls.append(message)
        return {"error": "worker 未启动"}

    def reset(self):
        pass


class AgentConfigPanelRequestLifecycleTest(unittest.TestCase):
    def setUp(self):
        _app()
        self.panel = AgentConfigPanel(llm_client=_FakeClient())
        self.panel._worker_ready = True
        self.panel._sync_mode_state()

    def _make_stale_worker(self):
        worker = _LLMHttpWorker(
            self.panel._llm_client,
            "old request",
            self.panel._current_athlete_profile(),
            request_id=1,
        )
        self.panel._llm_worker = worker
        self.panel._active_request_id = 2
        return worker

    def test_stale_finished_signal_clears_worker_reference(self):
        worker = self._make_stale_worker()
        worker.finished.connect(self.panel._on_llm_finished)

        worker.finished.emit(None, "old reply")

        self.assertIsNone(self.panel._llm_worker)
        self.assertEqual(self.panel._chat_display.toPlainText(), "")
        self.assertTrue(self.panel._chat_input.isEnabled())

    def test_stale_error_signal_clears_worker_reference(self):
        worker = self._make_stale_worker()
        worker.error.connect(self.panel._on_llm_error)

        worker.error.emit("old error")

        self.assertIsNone(self.panel._llm_worker)
        self.assertEqual(self.panel._chat_display.toPlainText(), "")
        self.assertTrue(self.panel._chat_input.isEnabled())

    def test_send_rechecks_worker_status_before_starting_http_worker(self):
        client = _RestartingClient()
        panel = AgentConfigPanel(llm_client=client)
        panel._worker_ready = True
        panel._sync_mode_state()
        panel._chat_input.setText("入门用户 3 次纵跳")

        panel._on_send_message()

        self.assertEqual(client.chat_calls, [])
        self.assertIsNone(panel._llm_worker)
        self.assertFalse(panel._worker_ready)
        self.assertNotIn("worker 未启动", panel._chat_display.toPlainText())
        self.assertIn("初始化", panel._status_label.text())


if __name__ == "__main__":
    unittest.main()
