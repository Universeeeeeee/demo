"""Tests for treadmill report data models and MetricSummary."""

import math

from config.treadmill_report import (
    TreadmillGaitReport,
    TreadmillRunningReport,
    TreadmillStepResult,
    summarize,
)


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
