import pytest

pytest.importorskip("dayu_widgets")

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication, QBoxLayout, QGridLayout

from config.test_config import TestConfig
from config.treadmill_config import TreadmillGaitConfig
from ui.footprint_channel import FootprintChannelWidget
from ui.views.execution_view import ExecutionView, MetricCard


def _app():
    return QApplication.instance() or QApplication([])


def test_metric_card_keeps_value_visible_when_unit_is_shown(qtbot):
    card = MetricCard("平均步速", "cm/s")
    qtbot.addWidget(card)
    card.resize(400, 130)
    card.show()
    QApplication.processEvents()

    assert card.minimumHeight() >= card.minimumSizeHint().height()
    assert card._value.height() >= card._value.sizeHint().height()
    assert card._unit.height() >= card._unit.sizeHint().height()


def test_execution_view_passes_treadmill_direction_to_footprint_channel():
    _app()
    view = ExecutionView()

    view.configure(
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Opposite side",
        )
    )

    assert view._footprint_channel._direction == "Opposite side"


def test_execution_view_shows_footprint_channel_for_treadmill(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.show()

    view.configure(
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )

    assert isinstance(view._footprint_channel, FootprintChannelWidget)
    assert view._footprint_channel.isVisible()
    assert not view._chart_container.isVisible()
    layout = view._lower_split.layout()
    assert isinstance(layout, QGridLayout)
    assert layout.getItemPosition(layout.indexOf(view._camera_panel)) == (0, 0, 2, 1)
    assert layout.getItemPosition(layout.indexOf(view._progress_container)) == (0, 1, 2, 1)
    assert layout.getItemPosition(layout.indexOf(view._footprint_channel)) == (0, 2, 1, 1)
    assert layout.getItemPosition(layout.indexOf(view._controls_container)) == (1, 2, 1, 1)
    assert layout.columnStretch(0) == 3
    assert layout.columnStretch(2) == 1


def test_gait_time_and_controls_use_vertical_lower_layout(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.resize(1600, 900)
    view.show()

    view.configure(
        TreadmillGaitConfig(
            stop_type="End of Time",
            test_length="01:00",
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )

    assert view._progress_bar.orientation() == Qt.Vertical
    assert view._progress_title.text() == "剩余"
    assert view._progress_value.text() == "01:00"
    assert view._progress_container.isVisible()
    assert view._progress_container.width() == 72
    assert view._controls_layout.direction() == QBoxLayout.TopToBottom
    assert view.btn_stop.text() == "结束"
    assert view._controls_container.geometry().left() == view._footprint_channel.geometry().left()
    assert view._controls_container.geometry().right() == view._footprint_channel.geometry().right()


def test_gait_running_controls_stack_in_right_column(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.show()
    view.configure(
        TreadmillGaitConfig(
            stop_type="End of Time",
            test_length="01:00",
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )

    view.on_device_state("connected", "设备已连接")
    view._on_start()
    view.on_session_started()

    assert not view.btn_start.isVisible()
    assert view.btn_pause.isVisible()
    assert view.btn_stop.isVisible()
    assert view._controls_layout.direction() == QBoxLayout.TopToBottom

    view._on_pause()
    assert "暂停分析（计时继续）" in view._mode_label.text()
    assert view.btn_pause.text() == "▶ 继续分析"


def test_execution_view_keeps_jump_charts_for_jump(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.show()
    config = TestConfig(test_type="Jump Test")

    view.configure(config)

    assert view._chart_container.isVisible()
    assert not view._footprint_channel.isVisible()
    assert view._progress_bar.orientation() == Qt.Horizontal
    assert view._controls_layout.direction() == QBoxLayout.LeftToRight


def test_execution_view_shows_current_and_completed_gait_cycles(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.show()
    view.configure(
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )

    view.on_gait_snapshot({
        "touch_count": 3,
        "stride_count": 0,
        "velocity_count": 0,
        "latest_extra_metrics": {},
        "gait_cycle_asymmetry_percent": {"gait_cycle_s": 4.5},
        "gait_cycle_state": {
            "support_state": "左脚单支撑",
            "completed_cycle_count": 1,
            "completed_cycle_start_index": 0,
            "current_cycles": {
                "left": {
                    "side": "left",
                    "start_time_s": 1.0,
                    "elapsed_s": 0.4,
                    "phase": "支撑相",
                }
            },
            "completed_cycles": [{
                "index": 0,
                "side": "right",
                "gait_cycle_s": 1.0,
                "stance_phase_s": 0.6,
                "swing_phase_s": 0.4,
                "total_double_support_s": 0.2,
            }],
        },
    })

    assert view._cycle_panel.isVisible()
    assert "左脚单支撑" in view._current_cycle_label.text()
    assert "左脚：支撑相 0.400 s" in view._current_cycle_label.text()
    assert view._completed_cycle_table.rowCount() == 1
    assert view._completed_cycle_table.item(0, 1).text() == "右脚"
    assert view._card_imbalance._title.text() == "步态周期不对称率"
    assert view._card_imbalance._value.text() == "4.5"

    view.on_gait_snapshot({
        "touch_count": 3,
        "stride_count": 0,
        "velocity_count": 0,
        "gait_cycle_asymmetry_percent": {"gait_cycle_s": 4.5},
        "gait_cycle_state": {
            "support_state": "腾空",
            "completed_cycle_count": 1,
            "completed_cycle_start_index": 1,
            "current_cycles": {},
            "completed_cycles": [],
        },
    })

    assert view._completed_cycle_table.rowCount() == 1


def test_completed_gait_cycles_show_newest_first_and_return_to_top(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.show()
    view.configure(
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )

    cycles = [
        {
            "index": index,
            "side": "left" if index % 2 == 0 else "right",
            "gait_cycle_s": 1.0,
            "stance_phase_s": 0.6,
            "swing_phase_s": 0.4,
            "total_double_support_s": 0.2,
        }
        for index in range(12)
    ]
    view._render_gait_cycle_state({
        "support_state": "腾空",
        "completed_cycle_count": 12,
        "completed_cycle_start_index": 0,
        "current_cycles": {},
        "completed_cycles": cycles,
    })

    table = view._completed_cycle_table
    assert table.item(0, 0).text() == "12"
    assert table.item(11, 0).text() == "1"

    table.scrollToBottom()
    QApplication.processEvents()
    assert table.verticalScrollBar().value() == table.verticalScrollBar().maximum()

    view._render_gait_cycle_state({
        "support_state": "左脚单支撑",
        "completed_cycle_count": 13,
        "completed_cycle_start_index": 12,
        "current_cycles": {},
        "completed_cycles": [{
            "index": 12,
            "side": "left",
            "gait_cycle_s": 1.1,
            "stance_phase_s": 0.7,
            "swing_phase_s": 0.4,
            "total_double_support_s": 0.2,
        }],
    })
    QApplication.processEvents()

    assert table.rowCount() == 13
    assert table.item(0, 0).text() == "13"
    assert table.item(1, 0).text() == "12"
    assert table.verticalScrollBar().value() == table.verticalScrollBar().minimum()


def test_execution_view_does_not_enable_cycle_panel_for_ground_gait(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.show()

    view.configure(TestConfig(test_type="Gait Test"))

    assert not view._cycle_panel.isVisible()


def test_execution_view_waits_for_device_and_session_started(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.configure(TestConfig(test_type="Jump Test"))

    assert not view.btn_start.isEnabled()
    assert view.btn_start.text() == "开始采集"

    view.on_device_state("connected", "设备已连接")
    assert view.btn_start.isEnabled()

    view._on_start()
    assert not view.btn_start.isEnabled()
    assert not view.btn_start.isHidden()
    assert view.btn_pause.isHidden()

    view.on_session_started()
    assert view.btn_start.isHidden()
    assert not view.btn_pause.isHidden()
    assert not view.btn_stop.isHidden()
