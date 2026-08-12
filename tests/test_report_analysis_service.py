"""Application-service tests for success, rejection and model failure paths."""

import sqlite3
import json

import pytest

from agent.report.service import ReportAnalysisError, ReportAnalysisService
from agent.report.skill_loader import ReportAnalysisSkillLoader
from agent.report.state import AnalysisStateReducer
from config.test_config import default_jump_config
from data.subject_store import SubjectStore
from reporting.models import (
    AnalysisNode,
    AnalysisQuestion,
    DataAccessScope,
    DraftAnalysisClaim,
    DraftAnalysisPackage,
    EvidenceReviewDecision,
    InvestigationDecision,
    HypothesisTarget,
    NextAnalysisAction,
    NumericBinding,
    PredicateBinding,
    SmallAnalysisPlan,
    SequentialAnalysisState,
    SequentialLoopCheckpoint,
    StopAnalysis,
)
from reporting.repository import ReportRepository
from reporting.kernel import ANALYSIS_METHOD_REGISTRY_VERSION, KERNEL_VERSION
from reporting.observation import OBSERVATION_BUILDER_VERSION
from reporting.tools import ANALYSIS_TOOL_REGISTRY_VERSION
from reporting.validators import ActionValidator
from tests.reporting_fixtures import make_jump_report


class _ServiceFakeAgent:
    model_name = "fake-model"
    prompt_version = "fake-prompt/1"

    def __init__(self, *, fail=False, invalid_claim=False):
        self.fail = fail
        self.invalid_claim = invalid_claim

    def propose_plan(self, observation, state):
        if self.fail:
            raise RuntimeError("model unavailable")
        record_set_id = observation.report_manifest.record_sets[0].record_set_id
        return InvestigationDecision(
            rationale="test",
            plan=SmallAnalysisPlan(
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
            ),
        )

    def review_evidence(self, observation, state, evidence):
        return EvidenceReviewDecision(evidence_sufficient=True, rationale="enough")

    def synthesize(self, observation, state, evidence):
        item = evidence[0].items[0]
        predicate_ref = next(
            predicate.predicate_evidence_id
            for predicate in item.predicates
            if predicate.predicate == "increase"
        )
        return DraftAnalysisPackage(
            summary="draft",
            claims=(
                DraftAnalysisClaim(
                    claim_id="c1",
                    claim_type="derived",
                    text_template=(
                        "后半程触地时间增加了0.1秒。"
                        if self.invalid_claim
                        else "后半程触地时间增加，前后差值为{difference}。"
                    ),
                    evidence_refs=(item.evidence_id,),
                    tool_run_ids=(item.tool_run_id,),
                    predicate_bindings=(PredicateBinding(predicate="increase", predicate_evidence_ref=predicate_ref),),
                    numeric_bindings=(
                        NumericBinding(binding_id="difference", source_type="evidence", source_ref=item.evidence_id, value_key="difference"),
                    ) if not self.invalid_claim else (),
                ),
            ),
        )


class _RepairingAgent(_ServiceFakeAgent):
    def __init__(self):
        super().__init__(invalid_claim=True)
        self.repair_calls = 0

    def repair_synthesis(
        self,
        observation,
        state,
        evidence,
        draft,
        error_code,
        error_message,
    ):
        self.repair_calls += 1
        self.invalid_claim = False
        return self.synthesize(observation, state, evidence)


class _SequentialServiceFakeAgent(_ServiceFakeAgent):
    sequential_prompt_version = "fake-sequential-prompt/1"

    def decide(self, observation, state, evidence, skill_context):
        if state.tool_call_count:
            return StopAnalysis(
                reason_code="evidence_sufficient",
                reason="证据充分",
            )
        record_set_id = observation.report_manifest.record_sets[0].record_set_id
        return NextAnalysisAction(
            action_id="a1",
            hypothesis=HypothesisTarget(
                hypothesis_id="h1",
                statement="触地时间是否增加",
                dimensions=("temporal",),
                metric_codes=("contact_time_s",),
                target_predicate="increase",
                reason="观察到候选变化",
                success_condition="获得方向证据",
            ),
            tool_name="analyze_current_session",
            analysis_method="verify_temporal_change",
            inputs={
                "record_set_id": record_set_id,
                "metric_codes": ["contact_time_s"],
            },
            purpose="验证时序变化",
        )

    def synthesize_sequential(
        self, observation, state, evidence, skill_context
    ):
        return self.synthesize(observation, state, evidence)


class _SequentialRepairingAgent(_SequentialServiceFakeAgent):
    def __init__(self):
        super().__init__(invalid_claim=True)
        self.synthesis_calls = 0
        self.repair_calls = 0

    def synthesize_sequential(
        self, observation, state, evidence, skill_context
    ):
        self.synthesis_calls += 1
        return self.synthesize(observation, state, evidence)

    def repair_synthesis(
        self,
        observation,
        state,
        evidence,
        draft,
        error_code,
        error_message,
    ):
        self.repair_calls += 1
        self.invalid_claim = False
        return self.synthesize(observation, state, evidence)


class _ProcessInterrupted(BaseException):
    pass


class _InterruptingRepository(ReportRepository):
    interrupt_phase = None

    def save_analysis_checkpoint(self, run_id, checkpoint):
        super().save_analysis_checkpoint(run_id, checkpoint)
        if checkpoint.phase == self.interrupt_phase:
            self.interrupt_phase = None
            raise _ProcessInterrupted(checkpoint.phase)


def _service(tmp_path, agent):
    store = SubjectStore(tmp_path / "service.sqlite3")
    session_id = store.record_session(
        None,
        default_jump_config(),
        make_jump_report([0.2] * 6 + [0.3] * 6),
    )
    repository = ReportRepository(store)
    return store, session_id, repository, ReportAnalysisService(repository, agent=agent)


def _statuses(store):
    with sqlite3.connect(store.db_path) as conn:
        return [row[0] for row in conn.execute("SELECT status FROM report_analyses ORDER BY id")]


def _metrics_rows(store):
    with sqlite3.connect(store.db_path) as conn:
        return [row[0] for row in conn.execute("SELECT run_metrics_json FROM report_analyses ORDER BY id")]


def test_service_returns_only_validated_rendered_analysis(tmp_path):
    store, session_id, repository, service = _service(tmp_path, _ServiceFakeAgent())

    result = service.analyze(session_id, DataAccessScope())

    assert result.claims[0].text.endswith("0.1 s。")
    assert result.cycle_count == 1
    assert _statuses(store) == ["validated"]
    assert _metrics_rows(store)[0] is not None
    metrics = json.loads(_metrics_rows(store)[0])
    assert metrics["analysis_tool_registry_version"] == "analysis-tool-registry/1.0"
    assert metrics["analysis_method_registry_version"] == "analysis-method-registry/1.0"
    assert metrics["kernel_version"] == "analysis-kernel/1.0"
    assert "operator_registry_version" not in metrics
    assert repository.get_latest_validated_analysis(
        session_id,
        DataAccessScope(),
        result.package_digest,
    )["analysis_run_id"] == result.analysis_run_id


def test_service_uses_sequential_loop_for_agent_with_decide(tmp_path):
    store, session_id, _, service = _service(
        tmp_path, _SequentialServiceFakeAgent()
    )

    result = service.analyze(session_id, DataAccessScope())

    assert result.claims[0].text.endswith("0.1 s。")
    assert result.cycle_count == 1
    assert result.replan_count == 0
    assert result.prompt_version == "fake-sequential-prompt/1"
    assert _statuses(store) == ["validated"]
    with sqlite3.connect(store.db_path) as conn:
        checkpoint_count = conn.execute(
            "SELECT COUNT(*) FROM report_analysis_checkpoints"
        ).fetchone()[0]
    assert checkpoint_count >= 4


def test_service_resumes_matching_running_action_checkpoint(tmp_path):
    agent = _SequentialServiceFakeAgent()
    store, session_id, repository, service = _service(tmp_path, agent)
    package = repository.get_package(session_id)
    record_set_id = package.record_sets[0].record_set_id
    action = NextAnalysisAction(
        action_id="a1",
        hypothesis=HypothesisTarget(
            hypothesis_id="h1",
            statement="触地时间是否增加",
            dimensions=("temporal",),
            metric_codes=("contact_time_s",),
            target_predicate="increase",
            reason="观察到候选变化",
            success_condition="获得方向证据",
        ),
        tool_name="analyze_current_session",
        analysis_method="verify_temporal_change",
        inputs={
            "record_set_id": record_set_id,
            "metric_codes": ["contact_time_s"],
        },
        purpose="验证时序变化",
    )
    validated = ActionValidator().validate_action(
        action, package, DataAccessScope()
    )
    context = ReportAnalysisSkillLoader().load_initial("Jump Test")
    state = AnalysisStateReducer().begin_action(
        SequentialAnalysisState(
            loaded_skill_references=context.loaded_reference_ids
        ),
        validated,
    )
    run_id = repository.create_analysis_run(
        session_id,
        DataAccessScope(),
        package.metadata.package_digest,
        model_name=agent.model_name,
        prompt_version=agent.sequential_prompt_version,
    )
    repository.save_analysis_checkpoint(
        run_id,
        SequentialLoopCheckpoint(
            phase="action_accepted",
            session_id=session_id,
            package_digest=package.metadata.package_digest,
            data_access_scope=DataAccessScope(),
            state=state,
            pending_action=validated,
            skill_version=context.skill_version,
            skill_content_digest=context.content_digest,
            observation_builder_version=OBSERVATION_BUILDER_VERSION,
            analysis_tool_registry_version=ANALYSIS_TOOL_REGISTRY_VERSION,
            analysis_method_registry_version=ANALYSIS_METHOD_REGISTRY_VERSION,
            kernel_version=KERNEL_VERSION,
        ),
    )

    result = service.analyze(session_id, DataAccessScope())

    assert result.analysis_run_id == run_id
    assert result.claims[0].text.endswith("0.1 s。")
    assert _statuses(store) == ["validated"]
    with sqlite3.connect(store.db_path) as conn:
        run_count = conn.execute(
            "SELECT COUNT(*) FROM report_analyses"
        ).fetchone()[0]
    assert run_count == 1


def test_service_resumes_claim_repair_without_repeating_synthesis_or_tools(
    tmp_path,
):
    store = SubjectStore(tmp_path / "claim-repair-resume.sqlite3")
    session_id = store.record_session(
        None,
        default_jump_config(),
        make_jump_report([0.2] * 6 + [0.3] * 6),
    )
    repository = _InterruptingRepository(store)
    repository.interrupt_phase = "claim_repair_pending"
    agent = _SequentialRepairingAgent()
    service = ReportAnalysisService(repository, agent=agent)

    with pytest.raises(_ProcessInterrupted):
        service.analyze(session_id, DataAccessScope())

    assert _statuses(store) == ["running"]
    assert agent.synthesis_calls == 1
    assert agent.repair_calls == 0
    with sqlite3.connect(store.db_path) as conn:
        tool_runs_before = conn.execute(
            "SELECT COUNT(*) FROM report_analysis_checkpoints"
        ).fetchone()[0]

    result = service.analyze(session_id, DataAccessScope())

    assert result.claims[0].text.endswith("0.1 s。")
    assert agent.synthesis_calls == 1
    assert agent.repair_calls == 1
    assert _statuses(store) == ["validated"]
    with sqlite3.connect(store.db_path) as conn:
        run_count = conn.execute(
            "SELECT COUNT(*) FROM report_analyses"
        ).fetchone()[0]
        checkpoint_count = conn.execute(
            "SELECT COUNT(*) FROM report_analysis_checkpoints"
        ).fetchone()[0]
    assert run_count == 1
    assert checkpoint_count > tool_runs_before


def test_service_allows_one_validator_guided_synthesis_repair(tmp_path):
    agent = _RepairingAgent()
    store, session_id, _, service = _service(tmp_path, agent)

    result = service.analyze(session_id, DataAccessScope())

    assert agent.repair_calls == 1
    assert result.claims[0].text.endswith("0.1 s。")
    assert _statuses(store) == ["validated"]


@pytest.mark.parametrize(
    "agent,expected_status,expected_code",
    [
        (_ServiceFakeAgent(fail=True), "failed", "analysis_failed"),
        (_ServiceFakeAgent(invalid_claim=True), "rejected", "unbound_numeric_literal"),
    ],
)
def test_service_never_persists_partial_text_on_failure(
    tmp_path, agent, expected_status, expected_code
):
    store, session_id, _, service = _service(tmp_path, agent)

    with pytest.raises(ReportAnalysisError) as exc_info:
        service.analyze(session_id, DataAccessScope())

    assert exc_info.value.code == expected_code
    assert _statuses(store) == [expected_status]
    assert _metrics_rows(store)[0] is not None


def test_service_rejects_external_scope_before_any_analysis_run(tmp_path):
    store, session_id, _, service = _service(tmp_path, _ServiceFakeAgent())

    with pytest.raises(ReportAnalysisError) as exc_info:
        service.analyze(session_id, DataAccessScope(longitudinal=True))

    assert exc_info.value.code == "external_scope_not_implemented"
    assert _statuses(store) == []


def test_disabled_external_tool_is_rejected_before_repository_detail_read():
    class _RepositorySpy:
        def __init__(self):
            self.package_reads = 0

        def get_package(self, session_id):
            self.package_reads += 1
            raise AssertionError("report detail must not be read")

    repository = _RepositorySpy()
    service = ReportAnalysisService(repository, agent=_ServiceFakeAgent())

    with pytest.raises(ReportAnalysisError) as exc_info:
        service.analyze(1, DataAccessScope(longitudinal=True))

    assert exc_info.value.code == "external_scope_not_implemented"
    assert repository.package_reads == 0


def test_service_defaults_to_ablation_b_execution_policy(tmp_path):
    _, _, _, service = _service(tmp_path, _ServiceFakeAgent())

    assert service._max_replans == 0
    assert service._observation_builder._include_analysis_sketch is True
    assert service._observation_builder._include_compact_series is True
    assert service._observation_builder._include_screening_cues is False
