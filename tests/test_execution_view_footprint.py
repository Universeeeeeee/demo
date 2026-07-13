import pytest

pytest.importorskip("dayu_widgets")

from qtpy.QtWidgets import QApplication

from config.test_config import TestConfig
from config.treadmill_config import TreadmillGaitConfig
from ui.footprint_channel import FootprintChannelWidget
from ui.views.execution_view import ExecutionView


def _app():
    return QApplication.instance() or QApplication([])


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
    assert view._lower_split.layout().stretch(0) == 3
    assert view._lower_split.layout().stretch(1) == 1


def test_execution_view_keeps_jump_charts_for_jump(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.show()
    config = TestConfig(test_type="Jump Test")

    view.configure(config)

    assert view._chart_container.isVisible()
    assert not view._footprint_channel.isVisible()
