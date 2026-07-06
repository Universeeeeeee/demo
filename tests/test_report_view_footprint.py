import pytest

pytest.importorskip("dayu_widgets")

from config.test_report import JumpTestReport
from config.treadmill_report import TreadmillGaitReport
from engine.footprint_visualization import FootprintVisualFrame
from ui.footprint_channel import FootprintReplayPanel
from ui.views.report_view import ReportView


def test_report_view_shows_replay_panel_for_treadmill_report(qtbot):
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
        visual_timeline=(FootprintVisualFrame(0.0, (0,) * 96),),
    )
    view = ReportView()
    qtbot.addWidget(view)
    view.show()

    view.load_report(report)

    assert isinstance(view._replay_panel, FootprintReplayPanel)
    assert view._replay_panel.isVisible()
    assert view._replay_panel._timeline[0]["timestamp_s"] == 0.0


def test_report_view_clears_treadmill_dynamic_widgets_when_loading_jump_report(qtbot):
    treadmill_report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
        metric_summaries={"contact_time_s": _summary()},
    )
    jump_report = JumpTestReport(
        touch_count=0,
        lift_count=0,
        air_times=(),
        contact_times=(),
        cycle_times=(),
        avg_jump_height=0.0,
        max_jump_height=0.0,
        avg_air_time=0.0,
        max_air_time=0.0,
        avg_contact_time=0.0,
        avg_cadence=None,
        finish_reason="manual",
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(treadmill_report)
    assert view._dynamic_widgets

    view.load_report(jump_report)

    assert view._dynamic_widgets == []


def _summary():
    from config.treadmill_report import MetricSummary

    return MetricSummary(
        count=1,
        mean=0.25,
        min=0.25,
        max=0.25,
        std=0.0,
        cv_percent=0.0,
    )
