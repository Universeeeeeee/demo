"""Main-window routing and two-stage test-flow regression tests."""

from __future__ import annotations

from qtpy.QtCore import QObject, Signal, Qt
from qtpy.QtTest import QSignalSpy
from qtpy.QtWidgets import QApplication, QInputDialog, QMessageBox

from config.test_config import default_jump_config
from config.test_report import JumpTestReport
from data.subject_store import SubjectStore
from ui.app_shell import MODULE_ATHLETES, MODULE_SETTINGS, MODULE_TEST
import ui.main_window as main_window_module
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
    led_health_changed = Signal(dict)
    session_started = Signal()
    session_finished = Signal(object)

    def __init__(self):
        super().__init__()
        self.is_running = False
        self.device_state = "disconnected"
        self.engine = None
        self.prepared = []
        self.device_connects = 0
        self.starts = 0
        self.stops = 0
        self.discards = 0
        self.health_refreshes = 0

    def ensure_device_connected(self):
        self.device_connects += 1
        self.device_state = "connected"
        self.device_state_changed.emit("connected", "设备已连接")

    def prepare(self, config):
        self.prepared.append(config)

    def start(self):
        self.starts += 1

    def retry_device(self):
        self.device_state = "connecting"

    def refresh_led_health(self):
        self.health_refreshes += 1

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


def test_main_window_requests_native_dark_title_bar(qtbot, tmp_path, monkeypatch):
    styled = []
    monkeypatch.setattr(
        main_window_module,
        "_apply_windows_dark_title_bar",
        lambda window: styled.append(window) or True,
    )

    window, _controller = _window(qtbot, tmp_path)

    assert styled == [window]
    assert window.windowTitle() == ""


def test_main_window_sets_brand_icon_for_window_and_application(qtbot, tmp_path):
    window, _controller = _window(qtbot, tmp_path)
    app_icon = QApplication.instance().windowIcon()

    assert not window.windowIcon().isNull()
    assert not app_icon.isNull()
    assert window.windowIcon().cacheKey() == app_icon.cacheKey()


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

    assert controller.device_connects == 1
    assert "设备已连接" in window._setup_view._device_state_label.text()

    controller.device_state_changed.emit("disconnected", "设备未连接")

    assert "设备未连接" in window._setup_view._device_state_label.text()
    assert window._setup_view.btn_ready.isEnabled()


def test_setup_device_refresh_routes_to_controller(qtbot, tmp_path):
    window, controller = _window(qtbot, tmp_path)

    qtbot.mouseClick(window._setup_view.btn_refresh_led_health, Qt.LeftButton)

    assert controller.health_refreshes == 1


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
    assert window._report_view._session_id == sessions[0].id
    assert sessions[0].subject_id is None
    assert sessions[0].team_id is None
    assert sessions[0].team_snapshot == {}
    assert sessions[0].subject_snapshot["age"] == 30


def test_team_identity_is_persisted_and_cleared_when_preparation_is_discarded(
    qtbot, tmp_path
):
    window, _controller = _window(qtbot, tmp_path)
    subject_id = window._subject_store.create_subject("Alice", 1990)
    alpha_id = window._subject_store.create_team("Alpha")
    window._subject_store.add_subject_to_team(subject_id, alpha_id)
    setup = SessionSetup(
        default_jump_config(),
        subject_id=subject_id,
        subject=window._subject_store.get_subject(subject_id),
        team_id=alpha_id,
        team_snapshot={"id": alpha_id, "name": "Alpha"},
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
    window._on_session_finished(report)

    session = window._subject_store.get_all_sessions()[0]
    assert session.team_id == alpha_id
    assert session.team_snapshot == {"id": alpha_id, "name": "Alpha"}

    window._on_ready(setup)
    window._discard_prepared_session()

    assert window._team_id is None
    assert window._team_snapshot is None


def test_registered_session_persists_snapshot_without_changing_master_profile(
    qtbot, tmp_path
):
    window, _controller = _window(qtbot, tmp_path)
    subject_id = window._subject_store.create_subject(
        "Alice",
        1990,
        height_cm=170.0,
        weight_kg=60.0,
        level="beginner",
        focus_side="left",
    )
    subject = window._subject_store.get_subject(subject_id)
    setup = SessionSetup(
        default_jump_config(),
        subject_id=subject_id,
        subject=subject,
        subject_snapshot={
            "display_name": "Alice",
            "age": 36,
            "height_cm": 180.0,
            "weight_kg": 70.0,
            "level": "advanced",
            "focus_side": "right",
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

    session = window._subject_store.get_all_sessions()[0]
    persisted_subject = window._subject_store.get_subject(subject_id)
    assert session.subject_snapshot["height_cm"] == 180.0
    assert session.subject_snapshot["weight_kg"] == 70.0
    assert persisted_subject.height_cm == 170.0
    assert persisted_subject.weight_kg == 60.0
    assert persisted_subject.level == "beginner"
    assert persisted_subject.focus_side == "left"
