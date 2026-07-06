"""Tests for treadmill report data models and MetricSummary."""

import math

import pytest

from config.treadmill_report import (
    TreadmillGaitReport,
    TreadmillRunningReport,
    TreadmillStepResult,
    summarize,
)
from engine.footprint_visualization import FootprintVisualFrame


def test_metric_summary_computes_population_std_and_cv():
    summary = summarize((1.0, 2.0, 3.0))

    assert summary.count == 3
    assert summary.mean == 2.0
    assert summary.min == 1.0
    assert summary.max == 3.0
    assert math.isclose(summary.std, math.sqrt(2 / 3))
    assert math.isclose(summary.cv_percent, math.sqrt(2 / 3) / 2.0 * 100)


def test_metric_summary_empty_values_return_none_metrics():
    summary = summarize(())

    assert summary.count == 0
    assert summary.mean is None
    assert summary.cv_percent is None


def test_treadmill_report_keeps_row_validity_and_config_snapshot():
    row = TreadmillStepResult(
        index=1,
        side="left",
        row_status="valid",
        is_event_valid=True,
        is_included_in_statistics=True,
        correction_source="none",
        contact_time_s=0.21,
        step_length_cm=72.0,
    )
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=1,
        lift_count=1,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        per_step_results=(row,),
        metric_summaries={"contact_time_s": summarize((0.21,))},
        report_config_snapshot={"treadmill_speed": 5.0},
    )

    assert report.test_type == "Treadmill Gait Test"
    assert report.per_step_results[0].is_included_in_statistics is True
    assert report.metric_summaries["contact_time_s"].mean == 0.21
    assert report.report_config_snapshot["treadmill_speed"] == 5.0


def test_running_report_uses_running_test_type():
    report = TreadmillRunningReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
        per_step_results=(),
        metric_summaries={},
        report_config_snapshot={},
    )

    assert report.test_type == "Treadmill Running Test"


def test_treadmill_report_defaults_visual_timeline_to_empty_tuple():
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
    )

    assert report.visual_timeline == ()


def test_treadmill_report_accepts_visual_timeline_frames():
    frame = FootprintVisualFrame(timestamp_s=0.0, contact_bits=(0,) * 96)
    report = TreadmillRunningReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
        visual_timeline=(frame,),
    )

    assert report.visual_timeline == (frame,)


def test_treadmill_metric_rows_include_validity_columns():
    pytest.importorskip("dayu_widgets", reason="UI dependency not installed")
    from ui.views.report_view import _treadmill_metric_rows

    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=1,
        lift_count=1,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        per_step_results=(
            TreadmillStepResult(
                index=1,
                side="left",
                row_status="valid",
                is_event_valid=True,
                is_included_in_statistics=True,
                correction_source="none",
                contact_time_s=0.25,
                step_length_cm=70.0,
            ),
        ),
        metric_summaries={},
        report_config_snapshot={"treadmill_speed": 5.0},
    )

    rows = _treadmill_metric_rows(report)

    assert rows == [[
        1, "left", "valid", True, True, 0.25, None,
        None, 70.0, None, None, "none", None, None,
    ]]


def test_treadmill_metric_rows_match_export_header_order():
    pytest.importorskip("dayu_widgets", reason="UI dependency not installed")
    from ui.views.report_view import TREADMILL_EXPORT_COLUMNS, _treadmill_metric_rows

    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=1,
        lift_count=1,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        per_step_results=(
            TreadmillStepResult(
                index=1,
                side="left",
                row_status="valid",
                is_event_valid=True,
                is_included_in_statistics=True,
                correction_source="none",
                contact_time_s=0.25,
                flight_time_s=0.05,
                step_time_s=0.70,
                step_length_cm=70.0,
                distance_cm=123.0,
                speed_m_s=1.5,
                step_reference_cm=42.0,
            ),
        ),
        metric_summaries={},
        report_config_snapshot={"treadmill_speed": 5.0},
    )

    row = _treadmill_metric_rows(report)[0]
    values = dict(zip(TREADMILL_EXPORT_COLUMNS, row))

    assert len(row) == len(TREADMILL_EXPORT_COLUMNS)
    assert values["flight_time_s"] == 0.05
    assert values["step_time_s"] == 0.70
    assert values["step_length_cm"] == 70.0
    assert values["step_reference_cm"] == 42.0
