"""Main-window routing and two-stage test-flow regression tests."""

from __future__ import annotations

from qtpy.QtCore import QObject, Signal
from qtpy.QtTest import QSignalSpy
from qtpy.QtWidgets import QApplication, QInputDialog, QMessageBox

from config.test_config import default_jump_config
from config.test_report import JumpTestReport
from data.subject_store import SubjectStore
from ui.app_shell import MODULE_ATHLETES, MODULE_SETTINGS, MODULE_TEST
from ui.main_window import MainWindow
from ui.views.athletes_view import _SubjectDialog
from ui.views.setup_view import SessionSetup


class _FakeLlmClient:
    is_running = False

    def start(self):
        return False

    def stop(self):
        self.is_running = False

    def worker_status(self, timeout=0.25):
        return "stopped"


class _FakeController(QObject):
    hop_event = Signal(object)
    gait_step_event = Signal(object)
    gait_snapshot = Signal(dict)
    footprint_visual_frame = Signal(dict)
    device_message = Signal(str)
    device_state_changed = Signal(str, str)
    session_started = Signal()
    session_finished = Signal(object)

    def __init__(self):
        super().__init__()
        self.is_running = False
        self.device_state = "connected"
        self.engine = None
        self.prepared = []
        self.starts = 0
        self.stops = 0
        self.discards = 0

    def prepare(self, config):
        self.prepared.append(config)

    def start(self):
        self.starts += 1

    def retry_device(self):
        self.device_state = "connecting"

    def stop(self, reason=None):
        self.stops += 1
        self.stop_reason = reason
        self.is_running = False

    def discard(self):
        self.discards += 1


def _window(qtbot, tmp_path):
    controller = _FakeController()
    window = MainWindow(
        subject_store=SubjectStore(tmp_path / "main.sqlite3"),
        llm_client=_FakeLlmClient(),
        controller=controller,
        enable_background_checks=False,
    )
    qtbot.addWidget(window)
    return window, controller


def test_application_navigation_routes_four_modules(qtbot, tmp_path):
    window, _controller = _window(qtbot, tmp_path)

    assert window._shell.sidebar.buttons[MODULE_TEST].isChecked()
    assert window._stack.currentWidget() is window._setup_view

    window._request_module(MODULE_ATHLETES)
    assert window._stack.currentWidget() is window._athletes_view
    assert window._shell.sidebar.buttons[MODULE_ATHLETES].isChecked()

    window._request_module(MODULE_SETTINGS)
    assert window._stack.currentWidget() is window._settings_view
    assert window._shell.sidebar.buttons[MODULE_SETTINGS].isChecked()


def test_application_dialogs_use_dark_theme(qtbot, tmp_path):
    window, _controller = _window(qtbot, tmp_path)
    window.show()

    athlete_dialog = _SubjectDialog(parent=window._athletes_view)
    input_dialog = QInputDialog(window._history_view)
    input_dialog.setLabelText("选择运动员：")
    input_dialog.setComboBoxItems(["张三", "李四"])
    message_box = QMessageBox(
        QMessageBox.Information,
        "提示",
        "系统消息框应保持深色主题。",
        QMessageBox.Ok | QMessageBox.Cancel,
        window,
    )

    for dialog in (athlete_dialog, input_dialog, message_box):
        qtbot.addWidget(dialog)
        dialog.show()
        QApplication.processEvents()
        background = dialog.grab().toImage().pixelColor(5, 5)
        assert background.lightness() < 80


def test_config_submission_enters_execution_without_starting_capture(qtbot, tmp_path):
    window, controller = _window(qtbot, tmp_path)
    setup = SessionSetup(default_jump_config())

    window._on_ready(setup)

    assert window._stack.currentWidget() is window._exec_view
    assert controller.prepared == [setup.config]
    assert controller.starts == 0

    window._exec_view._on_start()
    assert controller.starts == 1


def test_setup_device_status_tracks_controller_without_blocking_navigation(
    qtbot, tmp_path
):
    window, controller = _window(qtbot, tmp_path)
    window._setup_view._set_current_config(default_jump_config(), "manual")

    controller.device_state_changed.emit("disconnected", "设备未连接")

    assert "设备未连接" in window._setup_view._device_state_label.text()
    assert window._setup_view.btn_ready.isEnabled()


def test_prepared_session_can_return_to_config_without_report(qtbot, tmp_path):
    window, controller = _window(qtbot, tmp_path)
    window._on_ready(SessionSetup(default_jump_config()))

    window._exec_view.return_config_requested.emit()

    assert controller.discards == 1
    assert window._stack.currentWidget() is window._setup_view


def test_closing_prepared_session_discards_resources(qtbot, tmp_path):
    window, controller = _window(qtbot, tmp_path)
    window._on_ready(SessionSetup(default_jump_config()))

    window.close()

    assert controller.discards == 1


def test_running_session_rejects_or_confirms_navigation(
    qtbot, tmp_path, monkeypatch
):
    window, controller = _window(qtbot, tmp_path)
    window._on_ready(SessionSetup(default_jump_config()))
    controller.is_running = True

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No
    )
    window._request_module(MODULE_SETTINGS)
    assert window._stack.currentWidget() is window._exec_view
    assert controller.stops == 0

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes
    )
    window._request_module(MODULE_SETTINGS)
    assert controller.stops == 1
    assert window._stack.currentWidget() is window._settings_view


def test_running_session_can_end_and_mark_abnormal(qtbot, tmp_path, monkeypatch):
    window, controller = _window(qtbot, tmp_path)
    window._on_ready(SessionSetup(default_jump_config()))
    controller.is_running = True

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Abort
    )
    window._request_module(MODULE_SETTINGS)

    assert controller.stops == 1
    assert controller.stop_reason == "error"
    assert window._stack.currentWidget() is window._settings_view


def test_temporary_session_is_persisted_with_snapshot(qtbot, tmp_path):
    window, _controller = _window(qtbot, tmp_path)
    config = default_jump_config()
    setup = SessionSetup(
        config,
        subject_snapshot={
            "display_name": "临时测试",
            "age": 30,
            "height_cm": 170.0,
            "weight_kg": 70.0,
            "level": "intermediate",
            "focus_side": "",
        },
        config_source="manual",
    )
    report = JumpTestReport(
        touch_count=1,
        lift_count=1,
        air_times=(0.4,),
        contact_times=(0.2,),
        cycle_times=(0.6,),
        avg_jump_height=0.2,
        max_jump_height=0.2,
        avg_air_time=0.4,
        max_air_time=0.4,
        avg_contact_time=0.2,
        avg_cadence=100.0,
        finish_reason="manual",
    )

    window._on_ready(setup)
    window._on_session_started()
    window._on_session_finished(report)

    sessions = window._subject_store.get_all_sessions()
    assert len(sessions) == 1
    assert sessions[0].subject_id is None
    assert sessions[0].subject_snapshot["age"] == 30
