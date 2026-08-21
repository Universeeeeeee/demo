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
    ClaimRepairValidationError,
    ClaimRepairValidator,
    ClaimValidationError,
    ClaimValidator,
    PlanValidator,
)
from tests.reporting_fixtures import make_jump_package


def _evidence(package, *, node_id="n1", metric_code="contact_time_s"):
    record_set_id = package.record_sets[0].record_set_id
    plan = SmallAnalysisPlan(
        questions=(
            AnalysisQuestion(
                question_id=f"q-{node_id}",
                description="temporal",
                dimensions=("temporal",),
                metric_codes=(metric_code,),
                reason="synthetic",
                stop_condition="verified",
            ),
        ),
        nodes=(
            AnalysisNode(
                node_id=node_id,
                tool_name="analyze_current_session",
                analysis_method="verify_temporal_change",
                inputs={"record_set_id": record_set_id, "metric_codes": [metric_code]},
                question_id=f"q-{node_id}",
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


def test_numeric_binding_source_must_be_declared_by_claim():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    bundle = _evidence(package)
    item = bundle.items[0]
    fact = next(
        fact
        for fact in package.scalar_facts
        if fact.metric_code == "contact_time_s" and fact.statistic == "mean"
    )
    draft = DraftAnalysisPackage(
        summary="draft",
        claims=(
            DraftAnalysisClaim(
                claim_id="c1",
                claim_type="descriptive",
                text_template="数值为{difference}。",
                fact_refs=(fact.fact_id,),
                numeric_bindings=(
                    NumericBinding(
                        binding_id="difference",
                        source_type="evidence",
                        source_ref=item.evidence_id,
                        value_key="difference",
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ClaimValidationError) as exc_info:
        ClaimValidator().validate(draft, package, (bundle,), DataAccessScope())

    assert exc_info.value.code == "numeric_evidence_source_unbound"


def test_tool_run_ids_must_exactly_match_referenced_evidence():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    primary = _evidence(package, node_id="n1")
    extra = _evidence(package, node_id="n2", metric_code="air_time_s")
    item = primary.items[0]
    draft = DraftAnalysisPackage(
        summary="draft",
        claims=(
            DraftAnalysisClaim(
                claim_id="c1",
                claim_type="derived",
                text_template="触地时间增加。",
                evidence_refs=(item.evidence_id,),
                tool_run_ids=(item.tool_run_id, extra.items[0].tool_run_id),
                predicate_bindings=(
                    PredicateBinding(
                        predicate="increase",
                        predicate_evidence_ref=_predicate_ref(item, "increase"),
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ClaimValidationError) as exc_info:
        ClaimValidator().validate(
            draft, package, (primary, extra), DataAccessScope()
        )

    assert exc_info.value.code == "evidence_tool_run_unbound"


def test_duplicate_evidence_ids_are_rejected_before_mapping():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    bundle = _evidence(package)

    with pytest.raises(ClaimValidationError) as exc_info:
        ClaimValidator().validate(
            DraftAnalysisPackage(summary="draft", claims=()),
            package,
            (bundle, bundle),
            DataAccessScope(),
        )

    assert exc_info.value.code == "duplicate_evidence_id"


@pytest.mark.parametrize("template", ("{差值}", "{late-mean}"))
def test_non_ascii_or_non_identifier_placeholders_are_rejected(template):
    package = make_jump_package([0.2] * 12)
    fact = next(fact for fact in package.scalar_facts if fact.state == "present")
    draft = DraftAnalysisPackage(
        summary="draft",
        claims=(
            DraftAnalysisClaim(
                claim_id="c1",
                claim_type="descriptive",
                text_template=template,
                fact_refs=(fact.fact_id,),
            ),
        ),
    )

    with pytest.raises(ClaimValidationError) as exc_info:
        ClaimValidator().validate(draft, package, (), DataAccessScope())

    assert exc_info.value.code == "invalid_numeric_placeholder"


def test_blank_claim_template_and_invalid_binding_id_are_schema_errors():
    with pytest.raises(ValidationError):
        DraftAnalysisClaim(
            claim_id="c1",
            claim_type="descriptive",
            text_template=" ",
        )
    with pytest.raises(ValidationError):
        NumericBinding(
            binding_id="late-mean",
            source_type="fact",
            source_ref="fact-1",
        )


def test_numeric_repair_only_replaces_original_numeric_surface():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    bundle = _evidence(package)
    item = bundle.items[0]
    predicate = PredicateBinding(
        predicate="increase",
        predicate_evidence_ref=_predicate_ref(item, "increase"),
    )
    before = DraftAnalysisPackage(
        summary="draft",
        claims=(
            DraftAnalysisClaim(
                claim_id="c1",
                claim_type="derived",
                text_template="后半程触地时间增加了0.1秒。",
                evidence_refs=(item.evidence_id,),
                tool_run_ids=(item.tool_run_id,),
                predicate_bindings=(predicate,),
            ),
        ),
    )
    binding = NumericBinding(
        binding_id="difference",
        source_type="evidence",
        source_ref=item.evidence_id,
        value_key="difference",
    )
    repaired_claim = before.claims[0].model_copy(
        update={
            "text_template": "后半程触地时间增加了{difference}。",
            "numeric_bindings": (binding,),
        }
    )
    repaired = before.model_copy(update={"claims": (repaired_claim,)})

    ClaimRepairValidator().validate(
        before,
        repaired,
        "unbound_numeric_literal",
        package,
        (bundle,),
    )

    rewritten = before.model_copy(
        update={
            "claims": (
                repaired_claim.model_copy(
                    update={
                        "text_template": "另一个发现为{difference}。"
                    }
                ),
            )
        }
    )
    with pytest.raises(ClaimRepairValidationError):
        ClaimRepairValidator().validate(
            before,
            rewritten,
            "unbound_numeric_literal",
            package,
            (bundle,),
        )

    changed_value = before.model_copy(
        update={
            "claims": (
                repaired_claim.model_copy(
                    update={
                        "numeric_bindings": (
                            binding.model_copy(
                                update={"value_key": "second_mean"}
                            ),
                        )
                    }
                ),
            )
        }
    )
    with pytest.raises(ClaimRepairValidationError):
        ClaimRepairValidator().validate(
            before,
            changed_value,
            "unbound_numeric_literal",
            package,
            (bundle,),
        )

    changed_unit = before.model_copy(
        update={
            "claims": (
                before.claims[0].model_copy(
                    update={
                        "text_template": "后半程触地时间增加了0.1米。"
                    }
                ),
            )
        }
    )
    with pytest.raises(ClaimRepairValidationError):
        ClaimRepairValidator().validate(
            changed_unit,
            repaired,
            "unbound_numeric_literal",
            package,
            (bundle,),
        )


def test_conditional_repair_requires_resolvable_original_metric_set():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    bundle = _evidence(package)
    item = bundle.items[0]
    before = DraftAnalysisPackage(
        summary="draft",
        claims=(
            DraftAnalysisClaim(
                claim_id="c1",
                claim_type="derived",
                text_template="触地时间增加。",
                evidence_refs=("missing-evidence",),
                tool_run_ids=("missing-run",),
                predicate_bindings=(
                    PredicateBinding(
                        predicate="increase",
                        predicate_evidence_ref="missing-predicate",
                    ),
                ),
            ),
        ),
    )
    repaired_claim = before.claims[0].model_copy(
        update={
            "evidence_refs": (item.evidence_id,),
            "tool_run_ids": (item.tool_run_id,),
            "predicate_bindings": (
                PredicateBinding(
                    predicate="increase",
                    predicate_evidence_ref=_predicate_ref(item, "increase"),
                ),
            ),
        }
    )

    with pytest.raises(ClaimRepairValidationError):
        ClaimRepairValidator().validate(
            before,
            before.model_copy(update={"claims": (repaired_claim,)}),
            "unknown_evidence",
            package,
            (bundle,),
        )


@pytest.mark.parametrize(
    "error_code",
    (
        "unsupported_predicate",
        "invalid_numeric_evidence",
        "forbidden_claim_language",
        "scope_not_authorized",
        "snapshot_mismatch",
        "duplicate_claim_id",
    ),
)
def test_unsafe_claim_errors_are_not_repairable(error_code):
    assert ClaimRepairValidator.can_repair(error_code) is False
