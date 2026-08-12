"""Synthetic immutable report fixtures for deterministic Report Agent tests."""

from __future__ import annotations

from config.test_report import JumpResultRecord, JumpTestReport
from config.treadmill_report import (
    TreadmillGaitReport,
    TreadmillStepResult,
    summarize,
)
from reporting.builders import ReportDataPackageBuilder
from reporting.models import ReportContextInput


def make_jump_report(values: list[float], *, included: list[bool] | None = None):
    included = included or [True] * len(values)
    rows = tuple(
        JumpResultRecord(
            index=index + 1,
            lift_time_s=index * 0.6,
            touch_time_s=index * 0.6 + 0.4,
            air_time_s=0.4,
            jump_height_m=0.2,
            contact_time_s=value,
            cycle_time_s=0.6,
            cadence_jumps_per_min=100.0,
            is_included_in_statistics=included[index],
            statistics_exclusion_reason=None if included[index] else "synthetic_exclusion",
            quality_flags=() if included[index] else ("synthetic_exclusion",),
        )
        for index, value in enumerate(values)
    )
    return JumpTestReport(
        touch_count=len(rows),
        lift_count=len(rows),
        air_times=tuple(0.4 for _ in rows),
        contact_times=tuple(values),
        cycle_times=tuple(0.6 for _ in rows),
        avg_jump_height=0.2,
        max_jump_height=0.2,
        avg_air_time=0.4,
        max_air_time=0.4,
        avg_contact_time=sum(values) / len(values) if values else 0.0,
        avg_cadence=100.0,
        finish_reason="manual",
        jump_results=rows,
    )


def make_jump_package(values: list[float], *, included: list[bool] | None = None):
    return ReportDataPackageBuilder().build(
        make_jump_report(values, included=included),
        ReportContextInput(session_id=1, test_type="Jump Test"),
    )


def make_treadmill_report(
    left_contact: list[float],
    right_contact: list[float],
    left_step_length: list[float] | None = None,
    right_step_length: list[float] | None = None,
):
    left_step_length = left_step_length or [70.0] * len(left_contact)
    right_step_length = right_step_length or [70.0] * len(right_contact)
    rows = []
    for index in range(max(len(left_contact), len(right_contact))):
        for side, contacts, lengths in (
            ("left", left_contact, left_step_length),
            ("right", right_contact, right_step_length),
        ):
            if index >= len(contacts):
                continue
            rows.append(
                TreadmillStepResult(
                    index=len(rows) + 1,
                    side=side,
                    row_status="valid",
                    is_event_valid=True,
                    is_included_in_statistics=True,
                    correction_source="none",
                    time_s=len(rows) * 0.5,
                    contact_time_s=contacts[index],
                    step_length_cm=lengths[index],
                )
            )
    return TreadmillGaitReport(
        finish_reason="manual",
        touch_count=len(rows),
        lift_count=len(rows),
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        per_step_results=tuple(rows),
        metric_summaries={
            "contact_time_s": summarize(tuple(left_contact + right_contact)),
            "step_length_cm": summarize(tuple(left_step_length + right_step_length)),
        },
    )


def make_treadmill_package(
    left_contact: list[float],
    right_contact: list[float],
    left_step_length: list[float] | None = None,
    right_step_length: list[float] | None = None,
):
    return ReportDataPackageBuilder().build(
        make_treadmill_report(
            left_contact,
            right_contact,
            left_step_length,
            right_step_length,
        ),
        ReportContextInput(session_id=2, test_type="Treadmill Gait Test"),
    )
