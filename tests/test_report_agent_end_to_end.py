"""End-to-end deterministic acceptance tests for the Report Agent MVP."""

from pathlib import Path

from agent.report.service import ReportAnalysisService
from config.treadmill_config import TreadmillGaitConfig
from data.subject_store import SubjectStore
from reporting.models import (
    AnalysisNode,
    AnalysisQuestion,
    DataAccessScope,
    DraftAnalysisClaim,
    DraftAnalysisPackage,
    EvidenceReviewDecision,
    InvestigationDecision,
    NumericBinding,
    PredicateBinding,
    SmallAnalysisPlan,
)
from reporting.repository import ReportRepository
from tests.reporting_fixtures import make_treadmill_report
from tools.benchmark_report_agent import (
    ABLATIONS,
    TracedReportAgent,
    grade_initial_decision,
    load_report_agent_cases,
    load_report_analysis_skill,
)


class _CrossDimensionAgent:
    model_name = "fake-cross-dimension"
    prompt_version = "fake-cross-dimension/1"

    def propose_plan(self, observation, state):
        record_set = next(
            item
            for item in observation.report_manifest.record_sets
            if item.record_type == "step"
        )
        return InvestigationDecision(
            rationale="verify aligned cross-metric change",
            plan=SmallAnalysisPlan(
                questions=(
                    AnalysisQuestion(
                        question_id="q1",
                        description="触地时间与步长是否共同变化",
                        dimensions=("temporal", "cross_metric"),
                        metric_codes=("contact_time_s", "step_length_cm"),
                        reason="aligned segment observation",
                        stop_condition="co-change verified",
                    ),
                ),
                nodes=(
                    AnalysisNode(
                        node_id="n1",
                        tool_name="analyze_current_session",
                        analysis_method="verify_cross_metric_cochange",
                        inputs={
                            "record_set_id": record_set.record_set_id,
                            "metric_codes": ["contact_time_s", "step_length_cm"],
                        },
                        question_id="q1",
                        purpose="验证跨指标共同变化",
                    ),
                ),
            ),
        )

    def review_evidence(self, observation, state, evidence):
        return EvidenceReviewDecision(
            evidence_sufficient=True,
            rationale="deterministic co-change evidence available",
        )

    def synthesize(self, observation, state, evidence):
        item = evidence[0].items[0]
        predicate_ref = next(
            predicate.predicate_evidence_id
            for predicate in item.predicates
            if predicate.predicate == "co_change"
        )
        return DraftAnalysisPackage(
            summary="draft",
            claims=(
                DraftAnalysisClaim(
                    claim_id="c1",
                    claim_type="derived",
                    text_template="后半程触地时间与步长共同变化，触地时间差值为{ct_difference}，步长差值为{sl_difference}。",
                    evidence_refs=(item.evidence_id,),
                    tool_run_ids=(item.tool_run_id,),
                    predicate_bindings=(
                        PredicateBinding(
                            predicate="co_change",
                            predicate_evidence_ref=predicate_ref,
                        ),
                    ),
                    numeric_bindings=(
                        NumericBinding(
                            binding_id="ct_difference",
                            source_type="evidence",
                            source_ref=item.evidence_id,
                            value_key="contact_time_s_difference",
                        ),
                        NumericBinding(
                            binding_id="sl_difference",
                            source_type="evidence",
                            source_ref=item.evidence_id,
                            value_key="step_length_cm_difference",
                        ),
                    ),
                ),
            ),
        )


def test_fixed_benchmark_has_twelve_unique_cases_and_four_ablation_configs():
    cases = load_report_agent_cases()

    assert len(cases) == 12
    assert len({case.case_id for case in cases}) == 12
    assert set(ABLATIONS) == {"A", "B", "C", "D"}
    assert ABLATIONS["A"].include_sketch is False
    assert ABLATIONS["D"].max_replans == 1


def test_benchmark_trace_serializes_initial_decision_without_altering_it():
    agent = TracedReportAgent()
    decision = InvestigationDecision(
        rationale="baseline decision",
        plan=SmallAnalysisPlan(
            questions=(
                AnalysisQuestion(
                    question_id="q1",
                    description="是否存在后程变化",
                    dimensions=("temporal",),
                    metric_codes=("contact_time_s",),
                    reason="observation cue",
                    stop_condition="change verified",
                ),
            ),
            nodes=(
                AnalysisNode(
                    node_id="n1",
                    tool_name="analyze_current_session",
                    analysis_method="verify_temporal_change",
                    inputs={
                        "record_set_id": "records:jump_results",
                        "metric_codes": ["contact_time_s"],
                    },
                    question_id="q1",
                    purpose="验证后程变化",
                ),
            ),
        ),
    )
    agent.initial_decision = decision

    trace = agent.decision_trace()

    assert trace["initial_decision"]["rationale"] == "baseline decision"
    assert (
        trace["initial_decision"]["plan"]["nodes"][0]["analysis_method"]
        == "verify_temporal_change"
    )
    assert agent.initial_decision is decision


def test_runtime_skill_loader_discloses_only_matching_domain_reference():
    skill_path = (
        Path(__file__).resolve().parents[1]
        / "agent"
        / "report"
        / "skills"
        / "report-analysis"
    )

    content, audit = load_report_analysis_skill(
        skill_path, "Treadmill Gait Test"
    )

    assert "Treadmill Gait Analysis Prior" in content
    assert "Treadmill Running Analysis Prior" not in content
    assert "Jump Analysis Prior" not in content
    assert audit["loaded_references"] == ("references/gait.md",)
    assert len(audit["content_digest"]) == 64


def test_skill_decision_assertions_reject_batching_and_premature_robustness():
    case = load_report_agent_cases()[0]
    decision = InvestigationDecision(
        rationale="batch everything",
        plan=SmallAnalysisPlan(
            questions=(
                AnalysisQuestion(
                    question_id="q1",
                    description="是否变化",
                    dimensions=("temporal",),
                    metric_codes=("contact_time_s",),
                    reason="visible variation",
                    stop_condition="verified",
                ),
            ),
            nodes=(
                AnalysisNode(
                    node_id="n1",
                    tool_name="analyze_current_session",
                    analysis_method="verify_temporal_change",
                    inputs={
                        "record_set_id": "records:jump_results",
                        "metric_codes": ["contact_time_s"],
                    },
                    question_id="q1",
                    purpose="验证变化",
                ),
                AnalysisNode(
                    node_id="n2",
                    tool_name="analyze_current_session",
                    analysis_method="verify_exclusion_robustness",
                    inputs={
                        "record_set_id": "records:jump_results",
                        "metric_codes": ["contact_time_s"],
                    },
                    question_id="q1",
                    purpose="过早验证稳健性",
                ),
            ),
        ),
    )

    assertions = grade_initial_decision(case, decision)

    assert assertions["acceptable_first_action"] is True
    assert assertions["bounded_initial_action"] is False
    assert assertions["no_initial_exclusion_robustness"] is False


def test_cross_dimension_service_flow_binds_two_metrics_without_causal_claim(tmp_path):
    report = make_treadmill_report(
        [0.20] * 3 + [0.30] * 3,
        [0.20] * 3 + [0.30] * 3,
        [72.0] * 3 + [66.0] * 3,
        [72.0] * 3 + [66.0] * 3,
    )
    store = SubjectStore(tmp_path / "end-to-end.sqlite3")
    session_id = store.record_session(
        None,
        TreadmillGaitConfig(
            stop_type="End of Time",
            test_length="01:00",
            treadmill_speed=5.0,
            direction="Interface side",
        ),
        report,
    )
    service = ReportAnalysisService(
        ReportRepository(store),
        agent=_CrossDimensionAgent(),
    )

    result = service.analyze(session_id, DataAccessScope())

    assert result.cycle_count == 1
    assert result.replan_count == 0
    assert result.claims[0].predicate_bindings[0].predicate == "co_change"
    assert "0.1 s" in result.claims[0].text
    assert "-6 cm" in result.claims[0].text
    assert "导致" not in result.claims[0].text
    assert "因果" not in result.claims[0].text
