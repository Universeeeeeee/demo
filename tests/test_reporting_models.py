"""Validation contracts for semantic report evidence models."""

import math

import pytest
from pydantic import ValidationError

from reporting.metric_catalog import METRIC_CATALOG
from reporting.models import (
    AnalysisNode,
    AnalysisState,
    DataAccessScope,
    MetricValue,
    ScalarFact,
    ToolRunRecord,
)


def test_metric_catalog_codes_are_unique_and_units_are_explicit():
    assert len(METRIC_CATALOG) == len(set(METRIC_CATALOG))
    assert all(metric.unit for metric in METRIC_CATALOG.values())
    assert all(metric.record_types for metric in METRIC_CATALOG.values())


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_present_metric_value_rejects_non_finite_numbers(value):
    with pytest.raises(ValidationError):
        MetricValue(metric_code="contact_time_s", value=value)


def test_missing_metric_value_requires_reason_and_no_numeric_value():
    with pytest.raises(ValidationError):
        MetricValue(metric_code="contact_time_s", state="missing")
    with pytest.raises(ValidationError):
        MetricValue(
            metric_code="contact_time_s",
            value=0.0,
            state="missing",
            reason="not_recorded",
        )


def test_missing_scalar_fact_is_not_converted_to_zero():
    fact = ScalarFact(
        fact_id="fact-1",
        metric_code="contact_time_s",
        statistic="mean",
        unit="s",
        sample_count=0,
        state="missing",
        missing_reason="no_valid_observations",
        source_ref="report:contact_time_s:mean",
    )
    assert fact.value is None


def test_current_session_scope_cannot_be_disabled():
    with pytest.raises(ValidationError):
        DataAccessScope(current_session=False)


def test_legacy_analysis_state_shape_is_unchanged_by_sequential_state_work():
    assert set(AnalysisState().model_dump()) == {
        "cycle_count",
        "replan_count",
        "question_ids",
        "supported_predicates",
        "rejected_predicates",
        "inconclusive_predicates",
        "evidence_refs",
        "unresolved_questions",
        "limitations",
    }


def test_legacy_analysis_node_reads_old_fields_but_serializes_only_v2_fields():
    node = AnalysisNode.model_validate(
        {
            "node_id": "n1",
            "operator": "verify_temporal_change",
            "inputs": {},
            "data_scope": "current_session",
            "dependencies": [],
            "question_id": "q1",
            "purpose": "legacy",
        }
    )
    dumped = node.model_dump(mode="json")

    assert node.tool_name == "analyze_current_session"
    assert node.analysis_method == "verify_temporal_change"
    assert "operator" not in dumped
    assert "data_scope" not in dumped


def test_agent_cannot_supply_legacy_permission_field_with_v2_tool_name():
    with pytest.raises(ValidationError):
        AnalysisNode(
            node_id="n1",
            tool_name="analyze_current_session",
            analysis_method="quality_scope_check",
            inputs={},
            data_scope="longitudinal",
            question_id="q1",
            purpose="attempt permission override",
        )


def test_legacy_tool_run_preserves_digest_and_does_not_fabricate_input_digest():
    legacy_digest = "a" * 64
    run = ToolRunRecord.model_validate(
        {
            "tool_run_id": "run-1",
            "operator": "verify_temporal_change",
            "operator_version": "analysis-kernel/1.0",
            "data_scope": "current_session",
            "input_refs": ["record-1"],
            "output_refs": ["evidence-1"],
            "parameters": {},
            "output_digest": legacy_digest,
        }
    )
    dumped = run.model_dump(mode="json")

    assert run.tool_version == "legacy-tool/1.0"
    assert run.analysis_method_version == "analysis-kernel/1.0"
    assert run.kernel_version is None
    assert run.input_digest is None
    assert run.output_digest == legacy_digest
    assert "operator" not in dumped
    assert "operator_version" not in dumped
