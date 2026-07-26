"""Tests for the setup view config summary."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
)

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
    assert "速度：5.5 km/h" in summary_text
    assert "方向：Interface side" in summary_text
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
    assert "● 设备将在测试界面检查" not in labels
    assert view.findChild(QFrame, "ConfigSummaryCard") is not None
    assert (
        view._status_bar.sizePolicy().verticalPolicy()
        == QSizePolicy.Preferred
    )


def test_new_subject_dialog_uses_complete_dark_theme():
    _app()
    view = SetupView()

    dialog, _name, birth_year, _level = view._build_new_subject_dialog()

    assert dialog.objectName() == "NewSubjectDialog"
    assert "#121923" in dialog.styleSheet()
    assert isinstance(birth_year, QSpinBox)
    assert "QSpinBox" in dialog.styleSheet()


def test_config_summary_is_readable_and_structured():
    app = _app()
    view = SetupView()
    config = RuntimeTestConfig(
        start_type="Status change",
        stop_type="Status change",
        number_of_jumps=3,
    )

    view._set_current_config(config, "manual")
    view.show()
    app.processEvents()

    assert view._summary_label.font().pixelSize() >= 13
    assert "配置方式：手动配置" in view._summary_label.text()
    assert "测试模式：纵跳" in view._summary_label.text()
    assert "启动：Status change" in view._summary_label.text()
    assert "\n" in view._summary_label.text()
    assert view._summary_label.height() >= view._summary_label.sizeHint().height()


def test_all_config_sources_use_final_validation():
    _app()
    view = SetupView()
    invalid = RuntimeTestConfig(stop_type="Status change", number_of_jumps=None)

    for source in ("agent", "manual", "history", "last_session"):
        view._set_current_config(invalid, source)
        assert not view.btn_ready.isEnabled()
        assert view._config_errors


def test_ready_button_is_outside_summary_and_fixed_to_bottom_right(qtbot):
    view = SetupView()
    qtbot.addWidget(view)
    view.resize(1200, 720)
    view.show()
    QApplication.processEvents()

    assert not view._status_bar.isAncestorOf(view.btn_ready)
    assert view.rect().right() - view.btn_ready.geometry().right() <= 30
    assert view.rect().bottom() - view.btn_ready.geometry().bottom() <= 30


def test_filter_summary_expands_only_when_defaults_change():
    _app()
    view = SetupView()
    default_config = TreadmillGaitConfig(
        stop_type="End of Time",
        test_length="01:00",
        treadmill_speed=3.0,
        direction="Opposite side",
    )

    view._set_current_config(default_config, "manual")

    assert view._filter_state_label.text() == "默认配置"
    assert view._filter_details_label.isHidden()

    changed_config = TreadmillGaitConfig(
        stop_type="End of Time",
        test_length="01:00",
        treadmill_speed=3.0,
        direction="Opposite side",
        min_contact_time=80,
    )
    view._set_current_config(changed_config, "manual")

    assert view._filter_state_label.text() == "已修改"
    assert not view._filter_details_label.isHidden()
    assert "接触阈值：80 ms" in view._filter_details_label.text()


def test_device_state_is_informational_and_does_not_block_preparation():
    _app()
    view = SetupView()
    view._set_current_config(
        TreadmillGaitConfig(
            stop_type="End of Time",
            test_length="01:00",
            treadmill_speed=3.0,
            direction="Opposite side",
        ),
        "manual",
    )

    view.on_device_state("disconnected", "设备未连接")

    assert "设备未连接" in view._device_state_label.text()
    assert "标称采样率：1000 Hz" in view._device_meta_label.text()
    assert view.btn_ready.isEnabled()


def test_manual_config_scrollbar_stays_dark_at_minimum_window_size(qtbot):
    view = SetupView()
    qtbot.addWidget(view)
    view.resize(996, 560)
    view._set_config_mode(1)
    scroll = view.findChild(QScrollArea, "ManualConfigScroll")
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
    view.show()
    QApplication.processEvents()

    scrollbar = scroll.verticalScrollBar()
    assert scrollbar.isVisible()
    background = scrollbar.grab().toImage().pixelColor(2, 2)
    assert background.lightness() < 80
