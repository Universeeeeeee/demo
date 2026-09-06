"""Deterministic sequential hypothesis-state transition tests."""

import pytest

from agent.report.state import (
    AnalysisStateReducer,
    AnalysisStateReductionError,
    MAX_AGENT_DECISIONS,
    MAX_ANALYSIS_TOOL_CALLS,
)
from agent.report.tools import AnalysisToolGateway
from reporting.models import (
    DataAccessScope,
    HypothesisTarget,
    LoadSkillResource,
    NextAnalysisAction,
    StopAnalysis,
    SequentialAnalysisState,
)
from reporting.validators import ActionValidator
from tests.reporting_fixtures import make_jump_package


def _validated_action(package, target_predicate="increase", action_id="a1", hypothesis_id="h1"):
    record_set_id = package.record_sets[0].record_set_id
    action = NextAnalysisAction(
        action_id=action_id,
        hypothesis=HypothesisTarget(
            hypothesis_id=hypothesis_id,
            statement=f"触地时间是否满足{target_predicate}",
            dimensions=("temporal",),
            metric_codes=("contact_time_s",),
            target_predicate=target_predicate,
            reason="观察到候选时序差异",
            success_condition="获得精确Predicate Evidence",
        ),
        tool_name="analyze_current_session",
        analysis_method="verify_temporal_change",
        inputs={
            "record_set_id": record_set_id,
            "metric_codes": ["contact_time_s"],
        },
        purpose="验证时序方向",
    )
    return ActionValidator().validate_action(
        action,
        package,
        DataAccessScope(),
    )


def _execute(package, action):
    return AnalysisToolGateway().execute_action(
        package,
        action,
        DataAccessScope(),
    )


@pytest.mark.parametrize(
    "values,target_predicate,expected_status,legacy_field",
    [
        ([0.2] * 6 + [0.3] * 6, "increase", "supported", "supported_predicates"),
        ([0.2] * 6 + [0.3] * 6, "decrease", "not_supported", "rejected_predicates"),
        ([0.2, 0.21, 0.3, 0.31], "increase", "inconclusive", "inconclusive_predicates"),
    ],
)
def test_evidence_resolves_active_hypothesis_to_exact_four_state_outcome(
    values,
    target_predicate,
    expected_status,
    legacy_field,
):
    package = make_jump_package(values)
    action = _validated_action(package, target_predicate)
    reducer = AnalysisStateReducer()

    active = reducer.begin_action(SequentialAnalysisState(), action)
    resolved = reducer.apply_evidence(active, action, _execute(package, action))

    assert active.hypotheses[0].status == "active"
    assert resolved.hypotheses[0].status == expected_status
    assert resolved.tool_call_count == 1
    assert resolved.decision_count == 1
    assert resolved.hypotheses[0].evidence_refs == resolved.evidence_refs
    assert resolved.hypotheses[0].predicate_evidence_refs[0]
    assert getattr(resolved, legacy_field) == (
        f"{target_predicate}:contact_time_s",
    )


def test_state_reducer_rejects_duplicate_hypothesis_and_semantic_request():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action = _validated_action(package)
    reducer = AnalysisStateReducer()
    active = reducer.begin_action(SequentialAnalysisState(), action)
    repeated_hypothesis = action.model_copy(
        update={
            "action": action.action.model_copy(update={"action_id": "a2"}),
            "node": action.node.model_copy(update={"node_id": "a2"}),
        }
    )

    with pytest.raises(AnalysisStateReductionError) as duplicate_id:
        reducer.begin_action(active, repeated_hypothesis)

    assert duplicate_id.value.code == "duplicate_hypothesis_id"

    with pytest.raises(AnalysisStateReductionError) as duplicate_action:
        reducer.begin_action(active, action)

    assert duplicate_action.value.code == "duplicate_action_id"


def test_state_reducer_rejects_evidence_from_another_action():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action = _validated_action(package)
    reducer = AnalysisStateReducer()
    active = reducer.begin_action(SequentialAnalysisState(), action)
    bundle = _execute(package, action)
    wrong_item = bundle.items[0].model_copy(update={"node_id": "another-action"})
    wrong_bundle = bundle.model_copy(update={"items": (wrong_item,)})

    with pytest.raises(AnalysisStateReductionError) as exc_info:
        reducer.apply_evidence(active, action, wrong_bundle)

    assert exc_info.value.code == "evidence_action_mismatch"


def test_state_reducer_requires_exact_target_predicate_and_metric_binding():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action = _validated_action(package)
    reducer = AnalysisStateReducer()
    active = reducer.begin_action(SequentialAnalysisState(), action)
    bundle = _execute(package, action)
    predicates = tuple(
        predicate.model_copy(update={"metric_codes": ("air_time_s",)})
        if predicate.predicate == "increase"
        else predicate
        for predicate in bundle.items[0].predicates
    )
    wrong_item = bundle.items[0].model_copy(update={"predicates": predicates})

    with pytest.raises(AnalysisStateReductionError) as exc_info:
        reducer.apply_evidence(
            active,
            action,
            bundle.model_copy(update={"items": (wrong_item,)}),
        )

    assert exc_info.value.code == "target_predicate_not_resolved"


def test_state_reducer_rejects_same_semantic_request_under_new_ids():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    first = _validated_action(package)
    repeated = _validated_action(
        package,
        action_id="a2",
        hypothesis_id="h2",
    )
    reducer = AnalysisStateReducer()
    state = reducer.begin_action(SequentialAnalysisState(), first)

    with pytest.raises(AnalysisStateReductionError) as exc_info:
        reducer.begin_action(state, repeated)

    assert first.request_hash == repeated.request_hash
    assert exc_info.value.code == "duplicate_action_request"


def test_resolved_hypothesis_cannot_consume_evidence_twice():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action = _validated_action(package)
    reducer = AnalysisStateReducer()
    bundle = _execute(package, action)
    resolved = reducer.apply_evidence(
        reducer.begin_action(SequentialAnalysisState(), action),
        action,
        bundle,
    )

    with pytest.raises(AnalysisStateReductionError) as exc_info:
        reducer.apply_evidence(resolved, action, bundle)

    assert exc_info.value.code == "hypothesis_already_resolved"


def test_decision_and_tool_budgets_are_enforced_by_state():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action = _validated_action(package)
    reducer = AnalysisStateReducer()

    with pytest.raises(AnalysisStateReductionError) as decisions:
        reducer.begin_action(
            SequentialAnalysisState(decision_count=MAX_AGENT_DECISIONS),
            action,
        )
    with pytest.raises(AnalysisStateReductionError) as tools:
        reducer.begin_action(
            SequentialAnalysisState(tool_call_count=MAX_ANALYSIS_TOOL_CALLS),
            action,
        )

    assert decisions.value.code == "decision_budget_exhausted"
    assert tools.value.code == "tool_budget_exhausted"


def test_skill_and_stop_decisions_update_state_without_tool_calls():
    reducer = AnalysisStateReducer()
    loaded = reducer.record_skill_resource(
        SequentialAnalysisState(),
        LoadSkillResource(
            reference_id="references/evidence-guidelines.md",
            reason="准备综合结论",
        ),
    )
    stopped = reducer.record_stop(
        loaded,
        StopAnalysis(
            reason_code="no_high_value_hypothesis",
            reason="没有新的可验证假设",
            unresolved_hypothesis_ids=("h-pending",),
        ),
    )

    assert stopped.decision_count == 2
    assert stopped.tool_call_count == 0
    assert stopped.loaded_skill_references == (
        "references/evidence-guidelines.md",
    )
    assert stopped.stop_reason_code == "no_high_value_hypothesis"
    assert stopped.unresolved_questions == ("h-pending",)
