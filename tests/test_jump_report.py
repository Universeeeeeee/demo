"""Tests for JumpTestReport derived metrics."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.test_report import G, JumpTestReport, build_report
from ui.views.report_view import _jump_metric_rows


def _jump_height(air_time: float) -> float:
    return 0.5 * G * (air_time / 2) ** 2


def test_build_report_adds_jump_sequences_and_population_std_metrics():
    engine = SimpleNamespace(
        mode="\u7eb5\u8df3",
        touch_count=5,
        lift_count=4,
        air_times=[0.4, 0.6],
        contact_times=[0.2, 0.3, 0.5],
        cycle_times=[0.8, 1.2],
        export_frames=(),
        export_timestamps=(),
    )

    report = build_report(engine, reason="manual")

    assert isinstance(report, JumpTestReport)
    expected_heights = (_jump_height(0.4), _jump_height(0.6))
    assert report.jump_heights == expected_heights
    assert report.cadences == (75.0, 50.0)
    assert math.isclose(report.min_jump_height, expected_heights[0])
    assert math.isclose(report.max_jump_height, expected_heights[1])
    assert math.isclose(report.avg_jump_height, sum(expected_heights) / 2)
    expected_height_std = math.sqrt(
        sum((value - report.avg_jump_height) ** 2 for value in expected_heights) / 2
    )
    assert math.isclose(report.std_jump_height, expected_height_std)
    assert report.min_air_time == 0.4
    assert report.max_air_time == 0.6
    assert math.isclose(report.std_air_time, 0.1)
    assert report.min_contact_time == 0.2
    assert report.max_contact_time == 0.5
    expected_contact_std = math.sqrt(
        ((0.2 - (1.0 / 3)) ** 2 + (0.3 - (1.0 / 3)) ** 2 + (0.5 - (1.0 / 3)) ** 2) / 3
    )
    assert math.isclose(report.std_contact_time, expected_contact_std)
    assert report.avg_cadence == 60.0


def test_build_report_filters_non_positive_values_for_derived_jump_metrics():
    engine = SimpleNamespace(
        mode="\u7eb5\u8df3",
        touch_count=3,
        lift_count=3,
        air_times=[0.0, -0.1, 0.5],
        contact_times=[0.0, 0.25],
        cycle_times=[0.0, -1.0, 1.0],
        export_frames=(),
        export_timestamps=(),
    )

    report = build_report(engine, reason="manual")

    assert report.jump_heights == (_jump_height(0.5),)
    assert report.cadences == (60.0,)
    assert report.min_air_time == 0.5
    assert report.max_air_time == 0.5
    assert report.std_air_time == 0.0
    assert report.min_contact_time == 0.25
    assert report.max_contact_time == 0.25
    assert report.std_contact_time == 0.0
    assert report.avg_cadence == 60.0


def test_jump_metric_rows_expand_to_longest_sequence_without_zip_truncation():
    report = JumpTestReport(
        touch_count=3,
        lift_count=2,
        air_times=(0.4, 0.6),
        contact_times=(0.2,),
        cycle_times=(0.8, 1.2, 1.5),
        avg_jump_height=0.0,
        max_jump_height=0.0,
        avg_air_time=0.0,
        max_air_time=0.0,
        avg_contact_time=0.0,
        avg_cadence=None,
        finish_reason="manual",
        jump_heights=(0.1962, 0.44145),
        cadences=(75.0, 50.0, 40.0),
    )

    rows = _jump_metric_rows(report)

    assert rows == [
        [1, 0.4, 0.2, 0.8, 0.1962, 75.0],
        [2, 0.6, "", 1.2, 0.44145, 50.0],
        [3, "", "", 1.5, "", 40.0],
    ]
