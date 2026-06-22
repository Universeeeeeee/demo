"""Tests for the read-only history view."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qtpy.QtWidgets import QApplication

from config.test_config import TestConfig as _TestConfig
from config.test_report import JumpTestReport
from data.subject_store import SubjectStore
from ui.views.history_view import HistoryView


_APP = None


def _app():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
    else:
        _APP = app
    return _APP


def _jump_report(**overrides):
    values = {
        "touch_count": 5,
        "lift_count": 5,
        "air_times": (0.4, 0.42),
        "contact_times": (0.2, 0.21),
        "cycle_times": (0.6, 0.63),
        "avg_jump_height": 0.2,
        "max_jump_height": 0.22,
        "avg_air_time": 0.41,
        "max_air_time": 0.42,
        "avg_contact_time": 0.205,
        "avg_cadence": 95.0,
        "finish_reason": "jump_count_reached",
        "jump_heights": (0.18, 0.22),
        "cadences": (92.0, 98.0),
        "min_jump_height": 0.18,
        "std_jump_height": 0.02,
        "min_air_time": 0.4,
        "std_air_time": 0.01,
        "min_contact_time": 0.2,
        "max_contact_time": 0.21,
        "std_contact_time": 0.005,
        "export_frames": ([1, 0, 1],),
        "export_timestamps": (1.0,),
    }
    values.update(overrides)
    return JumpTestReport(**values)


class HistoryViewTest(unittest.TestCase):
    def setUp(self):
        _app()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "iron_jump.sqlite3"
        self.store = SubjectStore(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_load_subject_lists_sessions_and_emits_selected_config(self):
        subject_id = self.store.create_subject("Alice", 1990)
        result = self.store.search_subjects("Alice")[0]
        self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=3),
            _jump_report(touch_count=3),
            started_at="2026-05-14 09:00:00",
        )
        self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=6),
            _jump_report(touch_count=6, finish_reason="manual"),
            started_at="2026-05-14 11:00:00",
        )
        view = HistoryView(self.store)
        received = []
        view.load_config_requested.connect(received.append)

        view.load_subject(result)
        view._session_table.selectRow(0)
        view._on_load_config_clicked()

        self.assertEqual(view._session_table.rowCount(), 2)
        self.assertIn("Alice", view._subject_label.text())
        self.assertIn("手动结束", view._detail_label.text())
        self.assertIn("跳高标准差", view._detail_label.text())
        self.assertEqual(received[0].number_of_jumps, 6)


if __name__ == "__main__":
    unittest.main()
