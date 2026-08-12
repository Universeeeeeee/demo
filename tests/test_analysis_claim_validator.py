"""Evidence binding and unsupported-language tests for final Claims."""

import pytest
from pydantic import ValidationError

from agent.report.tools import AnalysisToolGateway
from reporting.models import (
    AnalysisNode,
    AnalysisQuestion,
    DataAccessScope,
    DraftAnalysisClaim,
    DraftAnalysisPackage,
    NumericBinding,
    PredicateBinding,
    SmallAnalysisPlan,
)
from reporting.validators import (
    ClaimValidationError,
    ClaimValidator,
    PlanValidator,
)
from tests.reporting_fixtures import make_jump_package


def _evidence(package):
    record_set_id = package.record_sets[0].record_set_id
    plan = SmallAnalysisPlan(
        questions=(
            AnalysisQuestion(
                question_id="q1",
                description="temporal",
                dimensions=("temporal",),
                metric_codes=("contact_time_s",),
                reason="synthetic",
                stop_condition="verified",
            ),
        ),
        nodes=(
            AnalysisNode(
                node_id="n1",
                tool_name="analyze_current_session",
                analysis_method="verify_temporal_change",
                inputs={"record_set_id": record_set_id, "metric_codes": ["contact_time_s"]},
                question_id="q1",
                purpose="verify",
            ),
        ),
    )
    validated = PlanValidator().validate(plan, package, DataAccessScope())
    return AnalysisToolGateway().execute_plan(
        package, validated, DataAccessScope()
    )


def _predicate_ref(item, name):
    return next(
        predicate.predicate_evidence_id
        for predicate in item.predicates
        if predicate.predicate == name
    )


def test_descriptive_fact_does_not_require_recalculation_tool():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    fact = next(
        fact for fact in package.scalar_facts
        if fact.metric_code == "contact_time_s" and fact.statistic == "mean"
    )
    draft = DraftAnalysisPackage(
        summary="draft",
        claims=(
            DraftAnalysisClaim(
                claim_id="c1",
                claim_type="descriptive",
                text_template="平均触地时间为{mean_ct}。",
                fact_refs=(fact.fact_id,),
                numeric_bindings=(
                    NumericBinding(binding_id="mean_ct", source_type="fact", source_ref=fact.fact_id),
                ),
            ),
        ),
    )

    validated = ClaimValidator().validate(draft, package, (), DataAccessScope())

    assert validated.claims[0].tool_run_ids == ()
    assert validated.claims[0].numeric_bindings[0].value == fact.value


def test_derived_claim_requires_supported_predicate_evidence_and_tool_run():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    bundle = _evidence(package)
    item = bundle.items[0]
    draft = DraftAnalysisPackage(
        summary="draft",
        claims=(
            DraftAnalysisClaim(
                claim_id="c1",
                claim_type="derived",
                text_template="后半程触地时间增加，前后差值为{difference}。",
                evidence_refs=(item.evidence_id,),
                tool_run_ids=(item.tool_run_id,),
                predicate_bindings=(PredicateBinding(predicate="increase", predicate_evidence_ref=_predicate_ref(item, "increase")),),
                numeric_bindings=(NumericBinding(binding_id="difference", source_type="evidence", source_ref=item.evidence_id, value_key="difference"),),
            ),
        ),
    )

    validated = ClaimValidator().validate(draft, package, (bundle,), DataAccessScope())

    assert validated.claims[0].numeric_bindings[0].unit == "s"


@pytest.mark.parametrize(
    "template,expected_code",
    [
        ("触地时间增加了0.1秒。", "unbound_numeric_literal"),
        ("触地时间增加导致受伤风险。", "forbidden_claim_language"),
    ],
)
def test_unbound_numbers_and_forbidden_language_are_rejected(template, expected_code):
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    bundle = _evidence(package)
    item = bundle.items[0]
    draft = DraftAnalysisPackage(
        summary="draft",
        claims=(
            DraftAnalysisClaim(
                claim_id="c1",
                claim_type="derived",
                text_template=template,
                evidence_refs=(item.evidence_id,),
                tool_run_ids=(item.tool_run_id,),
                predicate_bindings=(PredicateBinding(predicate="increase", predicate_evidence_ref=_predicate_ref(item, "increase")),),
            ),
        ),
    )

    with pytest.raises(ClaimValidationError) as exc_info:
        ClaimValidator().validate(draft, package, (bundle,), DataAccessScope())

    assert exc_info.value.code == expected_code


def test_unsupported_predicate_is_rejected():
    package = make_jump_package([0.3] * 6 + [0.2] * 6)
    bundle = _evidence(package)
    item = bundle.items[0]
    draft = DraftAnalysisPackage(
        summary="draft",
        claims=(
            DraftAnalysisClaim(
                claim_id="c1",
                claim_type="derived",
                text_template="触地时间增加。",
                evidence_refs=(item.evidence_id,),
                tool_run_ids=(item.tool_run_id,),
                predicate_bindings=(PredicateBinding(predicate="increase", predicate_evidence_ref=_predicate_ref(item, "increase")),),
            ),
        ),
    )

    with pytest.raises(ClaimValidationError) as exc_info:
        ClaimValidator().validate(draft, package, (bundle,), DataAccessScope())

    assert exc_info.value.code == "unsupported_predicate"


def test_predicate_name_must_match_exact_predicate_evidence():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    bundle = _evidence(package)
    item = bundle.items[0]
    draft = DraftAnalysisPackage(
        summary="draft",
        claims=(
            DraftAnalysisClaim(
                claim_id="c1",
                claim_type="derived",
                text_template="触地时间下降。",
                evidence_refs=(item.evidence_id,),
                tool_run_ids=(item.tool_run_id,),
                predicate_bindings=(
                    PredicateBinding(
                        predicate="decrease",
                        predicate_evidence_ref=_predicate_ref(
                            item,
                            "increase",
                        ),
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ClaimValidationError) as exc_info:
        ClaimValidator().validate(
            draft,
            package,
            (bundle,),
            DataAccessScope(),
        )

    assert exc_info.value.code == "predicate_binding_mismatch"


def test_predicate_binding_is_limited_to_mvp_whitelist():
    with pytest.raises(ValidationError):
        PredicateBinding(
            predicate="clinically_significant",
            predicate_evidence_ref="pe1",
        )
