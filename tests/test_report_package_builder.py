"""Deterministic conversion tests for immutable report snapshots."""

from dataclasses import asdict

import pytest

from config.test_report import (
    GaitTestReport,
    JumpResultRecord,
    JumpTestReport,
)
from config.treadmill_report import (
    GaitCycleRecord,
    TreadmillGaitReport,
    TreadmillRunningReport,
    TreadmillStepResult,
    summarize,
)
from reporting.builders import (
    ReportDataPackageBuilder,
    ReportManifestBuilder,
    UnsupportedReportTypeError,
)
from reporting.models import ReportContextInput


def _context(test_type: str, session_id: int = 1):
    return ReportContextInput(session_id=session_id, test_type=test_type)


def _jump_report():
    rows = (
        JumpResultRecord(
            index=1,
            lift_time_s=0.0,
            touch_time_s=0.42,
            air_time_s=0.42,
            jump_height_m=0.216,
            contact_time_s=0.20,
            cycle_time_s=0.62,
            cadence_jumps_per_min=96.77,
            is_included_in_statistics=True,
        ),
        JumpResultRecord(
            index=2,
            lift_time_s=0.7,
            touch_time_s=1.15,
            air_time_s=0.45,
            jump_height_m=0.248,
            contact_time_s=None,
            cycle_time_s=None,
            cadence_jumps_per_min=None,
            is_included_in_statistics=False,
            statistics_exclusion_reason="incomplete_cycle",
            quality_flags=("review_required",),
        ),
    )
    return JumpTestReport(
        touch_count=2,
        lift_count=2,
        air_times=(0.42, 0.45),
        contact_times=(0.20,),
        cycle_times=(0.62,),
        avg_jump_height=0.232,
        max_jump_height=0.248,
        avg_air_time=0.435,
        max_air_time=0.45,
        avg_contact_time=0.20,
        avg_cadence=96.77,
        finish_reason="manual",
        jump_heights=(0.216, 0.248),
        min_jump_height=0.216,
        std_jump_height=0.016,
        min_air_time=0.42,
        std_air_time=0.015,
        min_contact_time=0.20,
        max_contact_time=0.20,
        std_contact_time=0.0,
        jump_results=rows,
    )


def _treadmill_report(report_class=TreadmillGaitReport):
    rows = (
        TreadmillStepResult(
            index=1,
            side="left",
            row_status="valid",
            is_event_valid=True,
            is_included_in_statistics=True,
            correction_source="none",
            time_s=0.0,
            contact_time_s=0.25,
            step_length_cm=70.0,
        ),
        TreadmillStepResult(
            index=2,
            side="right",
            row_status="deleted",
            is_event_valid=True,
            is_included_in_statistics=False,
            correction_source="manual_delete_row",
            statistics_exclusion_reason="manual_delete_row",
            time_s=0.5,
            contact_time_s=0.27,
            step_length_cm=68.0,
            quality_flags=("manually_excluded",),
        ),
    )
    cycles = (
        GaitCycleRecord(
            index=1,
            side="left",
            start_time_s=0.0,
            end_time_s=1.0,
            gait_cycle_s=1.0,
            stance_phase_s=0.6,
            stance_phase_percent=60.0,
            swing_phase_s=0.4,
            swing_phase_percent=40.0,
            step_time_s=0.5,
            single_support_s=0.3,
            single_support_percent=30.0,
            total_double_support_s=0.2,
            total_double_support_percent=20.0,
            load_response_s=0.1,
            load_response_percent=10.0,
            pre_swing_s=0.1,
            pre_swing_percent=10.0,
            total_flight_time_s=None,
        ),
    )
    return report_class(
        finish_reason="manual",
        touch_count=2,
        lift_count=2,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        per_step_results=rows,
        gait_cycles=cycles,
        metric_summaries={"contact_time_s": summarize((0.25,))},
        cycle_metric_summaries={"gait_cycle_s": summarize((1.0,))},
    )


def test_jump_builder_preserves_order_missing_exclusion_and_input_snapshot():
    report = _jump_report()
    before = asdict(report)

    package = ReportDataPackageBuilder().build(report, _context("Jump Test"))

    assert asdict(report) == before
    records = package.record_sets[0].records
    assert [record.source_index for record in records] == [1, 2]
    assert records[0].timestamp_s == 0.0
    assert records[1].status.inclusion == "excluded"
    assert records[1].values["contact_time_s"].state == "missing"
    assert package.resolve_ref(records[1].record_id) is records[1]


@pytest.mark.parametrize(
    "report,test_type,expected_kind",
    [
        (_treadmill_report(), "Treadmill Gait Test", "treadmill_gait"),
        (
            _treadmill_report(TreadmillRunningReport),
            "Treadmill Running Test",
            "treadmill_running",
        ),
    ],
)
def test_treadmill_builder_preserves_side_alignment_and_zero_timestamp(
    report, test_type, expected_kind
):
    package = ReportDataPackageBuilder().build(report, _context(test_type))

    step_set = next(item for item in package.record_sets if item.record_type == "step")
    assert package.payload.kind == expected_kind
    assert [record.side for record in step_set.records] == ["left", "right"]
    assert step_set.records[0].timestamp_s == 0.0
    assert step_set.records[1].status.inclusion == "excluded"
    assert step_set.records[0].values["contact_time_s"].value == 0.25


def test_package_and_manifest_ids_are_stable_and_resolvable():
    builder = ReportDataPackageBuilder()
    package_a = builder.build(_jump_report(), _context("Jump Test"))
    package_b = builder.build(_jump_report(), _context("Jump Test"))
    manifest = ReportManifestBuilder().build(package_a)

    assert package_a == package_b
    assert package_a.metadata.package_digest == package_b.metadata.package_digest
    assert manifest.package_id == package_a.metadata.package_id
    assert all(package_a.resolve_ref(ref) is not None for ref in manifest.fact_refs)
    assert all(
        package_a.resolve_ref(item.record_set_id) is not None
        for item in manifest.record_sets
    )


def test_legacy_gait_report_is_explicitly_unsupported():
    report = GaitTestReport(
        touch_count=0,
        lift_count=0,
        stride_lengths=(),
        velocities=(),
        avg_stride=0.0,
        max_stride=0.0,
        avg_velocity=0.0,
        max_velocity=0.0,
    )
    with pytest.raises(UnsupportedReportTypeError):
        ReportDataPackageBuilder().build(report, _context("Jump Test"))
