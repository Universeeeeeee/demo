"""Tests for the LLM worker client lifecycle helpers."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.llm_client import LLMWorkerClient


class _FakeProcess:
    Running = 2

    def __init__(self, pid: int = 1234):
        self._pid = pid

    def state(self):
        return self.Running

    def processId(self):
        return self._pid


class _FakePySide6Process:
    class ProcessState:
        Running = "running"

    def __init__(self, pid: int = 1234):
        self._pid = pid

    def state(self):
        return self.ProcessState.Running

    def processId(self):
        return self._pid


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class LLMWorkerClientTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.port_file = Path(self.tmpdir.name) / "llm_port.json"
        self.client = LLMWorkerClient(
            python_exe=sys.executable,
            worker_script="worker.py",
            port_file=self.port_file,
        )
        self.client._process = _FakeProcess(pid=111)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_base_url_rejects_stale_port_file_from_other_process(self):
        self.port_file.write_text(json.dumps({"pid": 222, "port": 9876}))

        self.assertIsNone(self.client._base_url())

    def test_is_running_supports_pyside6_process_state_enum(self):
        self.client._process = _FakePySide6Process(pid=111)

        self.assertTrue(self.client.is_running)

    def test_worker_status_reports_warming_without_ready(self):
        self.port_file.write_text(json.dumps({"pid": 111, "port": 9876}))

        with patch("ui.llm_client.requests.get", return_value=_FakeResponse({"status": "warming"})):
            self.assertEqual(self.client.worker_status(), "warming")
            self.assertFalse(self.client.health_check())

    def test_worker_status_reports_ready(self):
        self.port_file.write_text(json.dumps({"pid": 111, "port": 9876}))

        with patch("ui.llm_client.requests.get", return_value=_FakeResponse({"status": "ready"})):
            self.assertEqual(self.client.worker_status(), "ready")
            self.assertTrue(self.client.health_check())


if __name__ == "__main__":
    unittest.main()
