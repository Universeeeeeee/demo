import pytest

pytest.importorskip("dayu_widgets")

from qtpy.QtWidgets import QApplication, QTableWidget

from config.test_report import JumpTestReport
from config.treadmill_report import TreadmillGaitReport
from engine.footprint_visualization import FootprintVisualFrame
from ui.footprint_channel import FootprintReplayPanel
from ui.views.report_view import ReportView, StatCard


def _app():
    return QApplication.instance() or QApplication([])


def test_report_view_passes_treadmill_direction_to_replay_panel():
    _app()
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
        report_config_snapshot={"direction": "Opposite side"},
        visual_timeline=(FootprintVisualFrame(0.0, (0,) * 96),),
    )
    view = ReportView()

    view.load_report(report)

    assert view._replay_panel._channel._direction == "Opposite side"


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


def test_treadmill_report_uses_overview_and_details_pages():
    _app()
    report = TreadmillGaitReport(
        finish_reason="time_up",
        touch_count=57,
        lift_count=56,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        metric_summaries={"contact_time_s": _summary()},
        left_right_results={"left": _summary(), "right": _summary()},
        report_config_snapshot={
            "treadmill_speed": 3.0,
            "direction": "Opposite side",
        },
        per_step_results=(
            _step(0, "left"),
            _step(1, "right"),
            _step(2, "left"),
        ),
        visual_timeline=(FootprintVisualFrame(0.0, (0,) * 96),),
    )
    view = ReportView()

    view.load_report(report)

    assert view._tabs.count() == 2
    assert view._tabs.tabText(0) == "概览"
    assert view._tabs.tabText(1) == "明细"
    assert view._overview_page.isAncestorOf(view._replay_panel)
    assert view._dynamic_widgets
    assert all(isinstance(widget, QTableWidget) for widget in view._dynamic_widgets)
    assert all(widget.parent() is view._details_content for widget in view._dynamic_widgets)


def test_treadmill_report_overview_keeps_tables_off_the_replay_page():
    _app()
    report = TreadmillGaitReport(
        finish_reason="time_up",
        touch_count=57,
        lift_count=56,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        metric_summaries={"contact_time_s": _summary()},
        report_config_snapshot={
            "treadmill_speed": 3.0,
            "direction": "Opposite side",
        },
        per_step_results=tuple(_step(i, "left" if i % 2 == 0 else "right") for i in range(57)),
        visual_timeline=(FootprintVisualFrame(0.0, (0,) * 96),),
    )
    view = ReportView()
    view.resize(1600, 900)
    view.load_report(report)
    view.show()
    QApplication.processEvents()

    assert view._tabs.currentWidget() is view._overview_page
    assert view._overview_page.isAncestorOf(view._replay_panel)
    assert not any(view._overview_page.isAncestorOf(widget) for widget in view._dynamic_widgets)
    assert view._replay_panel.width() <= 780
    assert view._replay_panel.height() >= 520


def test_stat_card_reduces_font_for_long_values():
    _app()
    card = StatCard("方向")

    card.set_value("Opposite side")

    assert "font-size: 18pt" in card._value.styleSheet()


def _step(index: int, side: str):
    from config.treadmill_report import TreadmillStepResult

    return TreadmillStepResult(
        index=index,
        side=side,
        row_status="valid",
        is_event_valid=True,
        is_included_in_statistics=True,
        correction_source="none",
        contact_time_s=0.25,
        flight_time_s=0.1,
        step_time_s=0.7,
        step_length_cm=60.0,
        step_reference_cm=40.0,
        speed_m_s=0.833,
    )


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
