"""Tests for the setup view config summary."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qtpy.QtWidgets import QApplication, QFrame, QLabel

from config.treadmill_config import TreadmillGaitConfig
from config.test_config import TestConfig as RuntimeTestConfig
from ui.views.setup_view import SetupView


_APP = None


def _app():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
    else:
        _APP = app
    return _APP


def test_setup_view_accepts_treadmill_gait_config_without_attribute_error():
    _app()
    view = SetupView()
    config = TreadmillGaitConfig(
        stop_type="End of Time",
        test_length="05:00",
        treadmill_speed=5.5,
        direction="Interface side",
    )

    view._set_current_config(config, "manual")

    summary_text = view._summary_label.text()
    assert "跑步机步态" in summary_text
    assert "速度 5.5 km/h" in summary_text
    assert "方向 Interface side" in summary_text
    assert view.btn_ready.isEnabled()


def test_manual_config_initializes_from_selected_agent_test_type():
    _app()
    view = SetupView()
    view._agent_panel._test_type_combo.setCurrentText("Treadmill Gait Test")

    view._set_config_mode(1)

    assert view.param_panel._test_type == "Treadmill Gait Test"
    assert "treadmill_speed" in view.param_panel._widgets
    assert "direction" in view.param_panel._widgets
    assert "start_type" not in view.param_panel._widgets
    assert view._current_config.test_type == "Treadmill Gait Test"


def test_setup_view_uses_application_page_header_and_two_stage_action():
    _app()
    view = SetupView()

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert "测试" in labels
    assert "配置测试参数并连接设备" in labels
    assert "IronJump 步态分析系统" not in labels
    assert view.btn_ready.text() == "进入测试准备"
    assert view._device_status_label.text() == "● 设备将在测试界面检查"
    assert view.findChild(QFrame, "ConfigSummaryCard") is not None


def test_all_config_sources_use_final_validation():
    _app()
    view = SetupView()
    invalid = RuntimeTestConfig(stop_type="Status change", number_of_jumps=None)

    for source in ("agent", "manual", "history", "last_session"):
        view._set_current_config(invalid, source)
        assert not view.btn_ready.isEnabled()
        assert view._config_errors
