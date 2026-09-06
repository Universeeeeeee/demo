"""Deterministic renderer tests for validated numeric bindings."""

from reporting.models import (
    AnalysisPackage,
    AnalysisState,
    DataAccessScope,
    LegacyPredicateBinding,
    PredicateBinding,
    ValidatedAnalysisClaim,
    ValidatedAnalysisPackage,
    ValidatedNumericBinding,
)
from reporting.renderer import AnalysisRenderer
from tests.reporting_fixtures import make_jump_package


def test_renderer_injects_bound_value_and_unit_deterministically():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    validated = ValidatedAnalysisPackage(
        summary="基于本次测试记录的受限证据分析。",
        claims=(
            ValidatedAnalysisClaim(
                claim_id="c1",
                claim_type="derived",
                text_template="前后差值为{difference}。",
                fact_refs=(),
                evidence_refs=("e1",),
                tool_run_ids=("t1",),
                predicate_bindings=(
                    PredicateBinding(
                        predicate="increase",
                        predicate_evidence_ref="predicate-evidence-1",
                    ),
                ),
                numeric_bindings=(
                    ValidatedNumericBinding(binding_id="difference", value=0.1, unit="s", source_ref="e1"),
                ),
                limitations=(),
            ),
        ),
        scope_expansion_suggestions=(),
        overall_limitations=(),
    )
    renderer = AnalysisRenderer()

    first = renderer.render(validated, analysis_run_id="run_1", package=package, access_scope=DataAccessScope(), state=AnalysisState(cycle_count=1), model_name="fake", prompt_version="v1")
    second = renderer.render(validated, analysis_run_id="run_1", package=package, access_scope=DataAccessScope(), state=AnalysisState(cycle_count=1), model_name="fake", prompt_version="v1")

    assert first == second
    assert first.analysis_schema_version == "analysis-schema/4.0"
    assert first.claims[0].text == "前后差值为0.1 s。"
    assert first.claims[0].citation_refs == ()
    assert first.claims[0].predicate_bindings[0].predicate_evidence_ref == (
        "predicate-evidence-1"
    )

    legacy = first.model_dump(mode="json")
    legacy.pop("analysis_schema_version")
    legacy.pop("prompt_content_digest")
    assert type(first).model_validate(legacy).analysis_schema_version == (
        "analysis-schema/1.0-legacy"
    )

    schema_v2 = first.model_dump(mode="json")
    schema_v2["analysis_schema_version"] = "analysis-schema/2.0"
    schema_v2["claims"][0]["predicate_bindings"] = [
        {"predicate": "increase", "evidence_ref": "e1"}
    ]
    parsed_v2 = AnalysisPackage.model_validate(schema_v2)
    assert isinstance(
        parsed_v2.claims[0].predicate_bindings[0],
        LegacyPredicateBinding,
    )


def test_renderer_uses_significant_digits_for_small_nonzero_values():
    assert AnalysisRenderer()._format_value(0.0004, "m") == "0.0004 m"
    assert AnalysisRenderer()._format_value(0.0000004, "m") == "4e-07 m"
