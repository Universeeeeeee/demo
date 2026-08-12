"""Tests for the deterministic Analytical Observation Layer."""

from __future__ import annotations

from config.test_report import JumpResultRecord, JumpTestReport
from reporting.builders import ReportDataPackageBuilder, ReportManifestBuilder
from reporting.models import (
    AnalysisMethodCapability,
    AnalysisToolCapability,
    DataAccessScope,
    DataScopeAvailability,
    ReportContextInput,
)
from reporting.observation import (
    OBSERVATION_TOKEN_BUDGET,
    ObservationBuilder,
    build_compact_session_series,
    estimate_observation_tokens,
    serialize_observation,
)


def _jump_report(count: int, *, excluded_index: int | None = None):
    rows = []
    for index in range(count):
        excluded = index == excluded_index
        rows.append(
            JumpResultRecord(
                index=index + 1,
                lift_time_s=index * 0.6,
                touch_time_s=index * 0.6 + 0.4,
                air_time_s=0.4 + index * 0.001,
                jump_height_m=0.2 + index * 0.001,
                contact_time_s=None if excluded else 0.2 + index * 0.001,
                cycle_time_s=None if excluded else 0.6,
                cadence_jumps_per_min=None if excluded else 100.0,
                is_included_in_statistics=not excluded,
                statistics_exclusion_reason="review" if excluded else None,
                quality_flags=("review_required",) if excluded else (),
            )
        )
    return JumpTestReport(
        touch_count=count,
        lift_count=count,
        air_times=tuple(row.air_time_s for row in rows),
        contact_times=tuple(
            row.contact_time_s for row in rows if row.contact_time_s is not None
        ),
        cycle_times=tuple(
            row.cycle_time_s for row in rows if row.cycle_time_s is not None
        ),
        avg_jump_height=0.2,
        max_jump_height=0.3,
        avg_air_time=0.4,
        max_air_time=0.5,
        avg_contact_time=0.2,
        avg_cadence=100.0,
        finish_reason="manual",
        jump_results=tuple(rows),
    )


def _package(count: int, *, excluded_index: int | None = None):
    return ReportDataPackageBuilder().build(
        _jump_report(count, excluded_index=excluded_index),
        ReportContextInput(session_id=1, test_type="Jump Test"),
    )


def _observation(count: int, *, excluded_index: int | None = None):
    package = _package(count, excluded_index=excluded_index)
    manifest = ReportManifestBuilder().build(package)
    capability = AnalysisToolCapability(
        tool_name="analyze_current_session",
        tool_version="analyze-current-session-tool/1.0",
        required_scope="current_session",
        enabled=True,
        available_methods=(
            AnalysisMethodCapability(
                analysis_method="verify_temporal_change",
                analysis_method_version="temporal-change-method/1.0",
                dimensions=("temporal",),
                enabled=True,
            ),
        ),
    )
    return package, ObservationBuilder().build(
        package,
        manifest,
        DataScopeAvailability(),
        DataAccessScope(),
        [capability],
    )


def test_observation_contains_manifest_sketch_series_quality_and_capabilities():
    package, observation = _observation(8, excluded_index=3)

    assert observation.report_manifest.package_id == package.metadata.package_id
    assert observation.authoritative_facts == package.scalar_facts
    assert observation.analysis_sketch.overall
    assert observation.analysis_sketch.temporal_segments
    assert observation.compact_session_series[0].rows
    assert observation.quality_summary.excluded_records == 1
    assert observation.available_analysis_capabilities[0].tool_name == "analyze_current_session"
    assert all(package.resolve_ref(ref) is not None for ref in observation.source_refs)


def test_screening_cues_are_neutral_and_not_evidence_objects():
    _, observation = _observation(8, excluded_index=3)
    allowed = {
        "quality_flag_present",
        "excluded_records_present",
        "missing_values_present",
        "segment_summary_available",
        "side_summary_available",
    }

    assert {cue.cue_code for cue in observation.screening_cues} <= allowed
    serialized = serialize_observation(observation)
    assert "退化" not in serialized
    assert "异常趋势" not in serialized
    assert "predicate" not in serialized.lower()


def test_compact_series_keeps_all_80_rows_and_samples_81_deterministically():
    package_80 = _package(80)
    package_81 = _package(81)

    series_80 = build_compact_session_series(package_80)[0]
    series_81_a = build_compact_session_series(package_81)[0]
    series_81_b = build_compact_session_series(package_81)[0]

    assert series_80.returned_rows == 80
    assert series_80.sampling_policy == "all_rows"
    assert series_81_a.returned_rows == 80
    assert series_81_a == series_81_b
    assert [row.ordinal for row in series_81_a.rows[:10]] == list(range(10))
    assert [row.ordinal for row in series_81_a.rows[-10:]] == list(range(71, 81))


def test_compact_series_preserves_metric_alignment_and_missing_placeholders():
    _, observation = _observation(8, excluded_index=3)
    row = observation.compact_session_series[0].rows[3]

    assert row.ordinal == 3
    assert row.inclusion == "excluded"
    assert row.values["air_time_s"] is not None
    assert row.values["contact_time_s"] is None


def test_observation_serialization_is_stable_and_parseable():
    _, observation_a = _observation(20)
    _, observation_b = _observation(20)

    serialized_a = serialize_observation(observation_a)
    serialized_b = serialize_observation(observation_b)

    assert serialized_a == serialized_b
    assert observation_a.model_validate_json(serialized_a) == observation_a
    assert estimate_observation_tokens(serialized_a) > 0


def test_budget_reduction_never_drops_authoritative_facts_or_quality():
    package, observation = _observation(200, excluded_index=100)

    assert observation.authoritative_facts == package.scalar_facts
    assert observation.quality_summary.excluded_records == 1
    assert observation.compact_session_series[0].returned_rows <= 80
    if estimate_observation_tokens(serialize_observation(observation)) > OBSERVATION_TOKEN_BUDGET:
        assert observation.compact_session_series[0].returned_rows == 20


def test_ablation_can_disable_sketch_series_and_cues_without_dropping_facts():
    package = _package(20, excluded_index=3)
    observation = ObservationBuilder(
        include_analysis_sketch=False,
        include_compact_series=False,
        include_screening_cues=False,
    ).build(
        package,
        ReportManifestBuilder().build(package),
        DataScopeAvailability(),
        DataAccessScope(),
        (),
    )

    assert observation.authoritative_facts == package.scalar_facts
    assert observation.analysis_sketch.overall == ()
    assert observation.compact_session_series == ()
    assert observation.screening_cues == ()
    assert observation.quality_summary.excluded_records == 1
