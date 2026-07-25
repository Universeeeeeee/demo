"""Regression tests for AgentConfigPanel request lifecycle handling."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qtpy.QtWidgets import QApplication

from config.treadmill_config import TreadmillGaitConfig
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

    def chat(self, message, athlete, agent_mode="jump"):
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

    def chat(self, message, athlete, agent_mode="jump"):
        self.chat_calls.append(message)
        return {"error": "worker 未启动"}


class _ModeCapturingClient:
    is_running = True

    def __init__(self):
        self.chat_calls = []

    def start(self):
        return True

    def worker_status(self, timeout=0.25):
        return "ready"

    def chat(self, message, athlete, agent_mode="jump"):
        self.chat_calls.append(
            {"message": message, "athlete": athlete, "agent_mode": agent_mode}
        )
        return {"reply": f"reply: {message}"}

    def reset(self):
        pass


class _TreadmillConfigClient(_ModeCapturingClient):
    def chat(self, message, athlete, agent_mode="jump"):
        self.chat_calls.append(
            {"message": message, "athlete": athlete, "agent_mode": agent_mode}
        )
        return {
            "reply": "configured",
            "config": {
                "test_type": "Treadmill Gait Test",
                "stop_type": "Software command",
                "test_length": None,
                "treadmill_speed": 5.5,
                "direction": "Interface side",
            },
        }

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

    def test_agent_panel_sends_treadmill_gait_agent_mode(self):
        client = _ModeCapturingClient()
        panel = AgentConfigPanel(llm_client=client)
        panel._worker_ready = True
        panel._sync_mode_state()
        panel._test_type_combo.setCurrentText("Treadmill Gait Test")
        panel._chat_input.setText("帮我配置跑步机步态测试")
        original_start = _LLMHttpWorker.start
        _LLMHttpWorker.start = lambda self: None
        try:
            panel._on_send_message()
        finally:
            _LLMHttpWorker.start = original_start

        self.assertIsNotNone(panel._llm_worker)
        self.assertEqual(panel._llm_worker._agent_mode, "treadmill_gait")

    def test_llm_worker_deserializes_treadmill_config_with_config_from_dict(self):
        client = _TreadmillConfigClient()
        worker = _LLMHttpWorker(
            client,
            "帮我配置跑步机步态测试",
            self.panel._current_athlete_profile(),
            agent_mode="treadmill_gait",
        )
        finished = []
        worker.finished.connect(lambda config, reply: finished.append((config, reply)))

        worker.run()

        self.assertEqual(client.chat_calls[0]["agent_mode"], "treadmill_gait")
        self.assertIsInstance(finished[0][0], TreadmillGaitConfig)
        self.assertEqual(finished[0][0].treadmill_speed, 5.5)

    def test_intelligent_config_hides_provider_and_offline_controls(self):
        self.panel.resize(900, 600)
        self.panel.show()
        QApplication.processEvents()

        self.assertFalse(hasattr(self.panel, "_mode_combo"))
        self.assertFalse(hasattr(self.panel, "_offline_btn"))
        self.assertEqual(self.panel._assistant_title.text(), "配置助手")
        self.assertGreaterEqual(
            self.panel._assistant_title.width(),
            self.panel._assistant_title.sizeHint().width(),
        )
        self.assertTrue(self.panel._status_label.isHidden())

    def test_intelligent_config_reflows_without_clipping_at_narrow_width(self):
        self.panel.setFixedSize(620, 480)
        self.panel.show()
        QApplication.processEvents()

        self.assertTrue(self.panel._compact_layout)
        self.assertGreaterEqual(
            self.panel._assistant_title.width(),
            self.panel._assistant_title.sizeHint().width(),
        )
        for card in (
            self.panel._profile_card,
            self.panel._chat_card,
            self.panel._suggestion_card,
        ):
            self.assertTrue(self.panel.rect().contains(card.geometry()))


if __name__ == "__main__":
    unittest.main()
