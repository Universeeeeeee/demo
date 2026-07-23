import pytest

pytest.importorskip("dayu_widgets")

from qtpy.QtWidgets import QApplication, QTableWidget

from config.test_report import JumpTestReport
from config.treadmill_report import GaitCycleRecord, TreadmillGaitReport, summarize
from engine.footprint_visualization import FootprintVisualFrame
from ui.footprint_channel import FootprintReplayPanel
from ui.views.report_view import CyclePhaseBar, ReportView, StatCard


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


def test_treadmill_report_shows_cycle_overview_timeline_and_details(qtbot):
    cycle = GaitCycleRecord(
        index=0,
        side="left",
        start_time_s=0.0,
        end_time_s=1.0,
        gait_cycle_s=1.0,
        stance_phase_s=0.6,
        stance_phase_percent=60.0,
        swing_phase_s=0.4,
        swing_phase_percent=40.0,
        step_time_s=0.5,
        single_support_s=0.4,
        single_support_percent=40.0,
        total_double_support_s=0.2,
        total_double_support_percent=20.0,
        load_response_s=0.1,
        load_response_percent=10.0,
        pre_swing_s=0.1,
        pre_swing_percent=10.0,
        total_flight_time_s=0.0,
    )
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=3,
        lift_count=2,
        resolved_starting_foot="left",
        starting_foot_source="manual_override",
        gait_cycles=(cycle,),
        cycle_metric_summaries={"gait_cycle_s": summarize((1.0,))},
        cycle_side_summaries={
            "left": {"gait_cycle_s": summarize((1.0,))},
            "right": {"gait_cycle_s": summarize(())},
        },
        report_config_snapshot={"treadmill_speed": 5.0, "direction": "Interface side"},
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)

    labels = [card._label.text() for card in view._stat_cards if card.isVisible()]
    assert "左脚有效周期" in labels
    assert "右脚有效周期" in labels
    assert "平均步态周期" in labels
    assert view._cycle_timeline_table.rowCount() == 1
    assert view._cycle_detail_table.rowCount() == 1
    assert view._cycle_detail_table.horizontalHeaderItem(1).text() == "脚"


def test_treadmill_report_shows_chinese_statistics_notes(qtbot):
    cycle = _cycle(
        is_included_in_statistics=False,
        statistics_exclusion_reason="Contact time below minimum threshold",
        quality_flags=("running_overlap_above_tolerance",),
    )
    step = _step(0, "left")
    step = type(step)(
        **{
            **step.__dict__,
            "gap_between_feet_cm": 8.5,
            "quality_flags": ("gap_below_minimum",),
        }
    )
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=3,
        lift_count=2,
        resolved_starting_foot="left",
        starting_foot_source="manual_override",
        per_step_results=(step,),
        gait_cycles=(cycle,),
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)

    timeline_note = _column_index(view._cycle_timeline_table, "统计说明")
    detail_note = _column_index(view._cycle_detail_table, "统计说明")
    step_gap = _column_index(view._treadmill_step_table, "两脚间距(cm)")
    step_note = _column_index(view._treadmill_step_table, "统计说明")
    assert (
        view._cycle_timeline_table.item(0, timeline_note).text()
        == "未纳入：触地时间低于最小阈值；质量提示：跑步时双脚重叠超过容差"
    )
    assert (
        view._cycle_detail_table.item(0, detail_note).text()
        == "未纳入：触地时间低于最小阈值；质量提示：跑步时双脚重叠超过容差"
    )
    assert view._treadmill_step_table.item(0, step_gap).text() == "8.500"
    assert (
        view._treadmill_step_table.item(0, step_note).text()
        == "质量提示：两脚间距低于最小阈值"
    )


def test_cycle_phase_bar_falls_back_when_detailed_stance_does_not_close():
    _app()
    cycle = _cycle(
        stance_phase_s=0.6,
        swing_phase_s=0.4,
        load_response_s=0.1,
        single_support_s=0.3,
        pre_swing_s=0.1,
    )

    bar = CyclePhaseBar(cycle)

    assert bar._segments() == [
        ("支撑相", 0.6),
        ("摆动相", 0.4),
    ]
    assert bar.toolTip() == "子阶段无法可靠拆分，按支撑相和摆动相绘制"


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


def _cycle(**overrides):
    values = {
        "index": 0,
        "side": "left",
        "start_time_s": 0.0,
        "end_time_s": 1.0,
        "gait_cycle_s": 1.0,
        "stance_phase_s": 0.6,
        "stance_phase_percent": 60.0,
        "swing_phase_s": 0.4,
        "swing_phase_percent": 40.0,
        "step_time_s": 0.5,
        "single_support_s": 0.4,
        "single_support_percent": 40.0,
        "total_double_support_s": 0.2,
        "total_double_support_percent": 20.0,
        "load_response_s": 0.1,
        "load_response_percent": 10.0,
        "pre_swing_s": 0.1,
        "pre_swing_percent": 10.0,
        "total_flight_time_s": 0.0,
    }
    values.update(overrides)
    return GaitCycleRecord(**values)


def _column_index(table, label):
    return next(
        index
        for index in range(table.columnCount())
        if table.horizontalHeaderItem(index).text() == label
    )
