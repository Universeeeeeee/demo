"""Bounded-cycle behavior tests using a deterministic Fake Report Agent."""

import pytest

from agent.report.analysis_loop import AnalysisLoop, AnalysisLoopError
from reporting.builders import ReportManifestBuilder
from reporting.kernel import AnalysisMethodRegistry
from reporting.models import (
    AnalysisNode,
    AnalysisQuestion,
    AnalysisState,
    DataAccessScope,
    DataScopeAvailability,
    DraftAnalysisPackage,
    EvidenceReviewDecision,
    InvestigationDecision,
    SmallAnalysisPlan,
)
from reporting.observation import ObservationBuilder
from reporting.tools import AnalysisToolRegistry
from tests.reporting_fixtures import make_jump_package


def _plan(
    package,
    metric_code="contact_time_s",
    node_id="n1",
    question_id="q1",
):
    record_set_id = package.record_sets[0].record_set_id
    return SmallAnalysisPlan(
        questions=(
            AnalysisQuestion(
                question_id=question_id,
                description="synthetic",
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
                inputs={
                    "record_set_id": record_set_id,
                    "metric_codes": [metric_code],
                },
                question_id=question_id,
                purpose="verify",
            ),
        ),
    )


class _FakeAgent:
    def __init__(self, package, *, replan=None, sufficient=True):
        self.package = package
        self.replan = replan
        self.sufficient = sufficient
        self.propose_calls = 0
        self.review_calls = 0
        self.synthesize_calls = 0

    def propose_plan(self, observation, state):
        self.propose_calls += 1
        return InvestigationDecision(plan=_plan(self.package), rationale="initial")

    def review_evidence(self, observation, state, evidence):
        self.review_calls += 1
        return EvidenceReviewDecision(
            evidence_sufficient=self.sufficient,
            rationale="review",
            replan=self.replan,
            unresolved_questions=("q1",) if not self.sufficient else (),
        )

    def synthesize(self, observation, state, evidence):
        self.synthesize_calls += 1
        return DraftAnalysisPackage(summary="draft", claims=())


def _observation(package):
    scope = DataAccessScope()
    return ObservationBuilder().build(
        package,
        ReportManifestBuilder().build(package),
        DataScopeAvailability(),
        scope,
        AnalysisToolRegistry().list_capabilities(
            package, scope, AnalysisMethodRegistry()
        ),
    )


def test_sufficient_evidence_stops_after_one_cycle():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    agent = _FakeAgent(package, sufficient=True)

    result = AnalysisLoop(agent).run(_observation(package), package, DataAccessScope())

    assert result.state.cycle_count == 1
    assert result.state.replan_count == 0
    assert len(result.evidence) == 1
    assert agent.propose_calls == agent.review_calls == agent.synthesize_calls == 1


def test_conflict_can_execute_exactly_one_distinct_replan():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    agent = _FakeAgent(
        package,
        sufficient=False,
        replan=_plan(
            package,
            metric_code="air_time_s",
            node_id="n2",
            question_id="q2",
        ),
    )

    result = AnalysisLoop(agent).run(_observation(package), package, DataAccessScope())

    assert result.state.cycle_count == 2
    assert result.state.replan_count == 1
    assert len(result.evidence) == 2
    assert agent.review_calls == 1


def test_duplicate_replan_is_rejected_instead_of_creating_a_third_loop():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    agent = _FakeAgent(
        package,
        sufficient=False,
        replan=_plan(package, node_id="n2", question_id="q2"),
    )

    with pytest.raises(AnalysisLoopError) as exc_info:
        AnalysisLoop(agent).run(_observation(package), package, DataAccessScope())

    assert exc_info.value.code == "duplicate_replan_request"
    assert exc_info.value.state.cycle_count == 1
    assert len(exc_info.value.evidence) == 1
    assert agent.synthesize_calls == 0


def test_incomplete_review_without_replan_stops_with_limitation():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    agent = _FakeAgent(package, sufficient=False, replan=None)

    result = AnalysisLoop(agent).run(_observation(package), package, DataAccessScope())

    assert result.state.cycle_count == 1
    assert "evidence_review_incomplete" in result.state.limitations
    assert result.state.unresolved_questions == ("q1",)


def test_inconclusive_evidence_is_not_recorded_as_rejected():
    package = make_jump_package([0.20, 0.21, 0.30, 0.31])
    agent = _FakeAgent(package, sufficient=True)

    result = AnalysisLoop(agent).run(
        _observation(package),
        package,
        DataAccessScope(),
    )

    key = "increase:contact_time_s"
    assert key in result.state.inconclusive_predicates
    assert key not in result.state.rejected_predicates


def test_ablation_can_disable_replan_without_changing_validator_or_kernel():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    agent = _FakeAgent(
        package,
        sufficient=False,
        replan=_plan(package, metric_code="air_time_s", node_id="n2"),
    )

    result = AnalysisLoop(agent, max_replans=0).run(
        _observation(package),
        package,
        DataAccessScope(),
    )

    assert result.state.cycle_count == 1
    assert result.state.replan_count == 0
    assert "replan_disabled_for_ablation" in result.state.limitations
