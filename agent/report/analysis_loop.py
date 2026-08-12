"""Bounded two-cycle hypothesis-verification loop for report analysis."""

from __future__ import annotations

from reporting.models import (
    AgentObservation,
    AnalysisState,
    DataAccessScope,
    EvidenceBundle,
    LoopResult,
    ReportDataPackage,
)
from reporting.validators import PlanValidationError, PlanValidator

from .tools import AnalysisToolGateway


MAX_INVESTIGATION_CYCLES = 2
MAX_REPLANS = 1
MAX_ANALYSIS_QUESTIONS_PER_CYCLE = 3
MAX_AGENT_LEVEL_NODES_PER_CYCLE = 3


class AnalysisLoopError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class AnalysisLoop:
    def __init__(
        self,
        agent,
        *,
        plan_validator: PlanValidator | None = None,
        tool_gateway: AnalysisToolGateway | None = None,
        max_replans: int = MAX_REPLANS,
    ):
        self._agent = agent
        self._plan_validator = plan_validator or PlanValidator()
        self._tool_gateway = tool_gateway or AnalysisToolGateway()
        if max_replans not in {0, 1}:
            raise ValueError("max_replans must be 0 or 1")
        self._max_replans = max_replans

    def run(
        self,
        observation: AgentObservation,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
    ) -> LoopResult:
        state = AnalysisState()
        evidence_bundles: list[EvidenceBundle] = []
        seen_request_hashes: set[str] = set()
        initial = self._agent.propose_plan(observation, state)
        validated = self._validate(initial.plan, package, access_scope)
        seen_request_hashes.update(validated.request_hashes)
        first_evidence = self._tool_gateway.execute_plan(
            package, validated, access_scope
        )
        evidence_bundles.append(first_evidence)
        state = self._updated_state(
            state,
            first_evidence,
            question_ids=tuple(
                question.question_id for question in initial.plan.questions
            ),
            cycle_count=1,
            replan_count=0,
        )

        review = self._agent.review_evidence(
            observation,
            state,
            tuple(evidence_bundles),
        )
        if (
            not review.evidence_sufficient
            and review.replan is not None
            and self._max_replans == 1
        ):
            validated_replan = self._validate(
                review.replan, package, access_scope
            )
            duplicate_hashes = seen_request_hashes.intersection(
                validated_replan.request_hashes
            )
            if duplicate_hashes:
                raise AnalysisLoopError(
                    "duplicate_replan_request",
                    "Replan repeated an already executed semantic request",
                )
            second_evidence = self._tool_gateway.execute_plan(
                package, validated_replan, access_scope
            )
            evidence_bundles.append(second_evidence)
            state = self._updated_state(
                state,
                second_evidence,
                question_ids=tuple(
                    question.question_id
                    for question in review.replan.questions
                ),
                cycle_count=2,
                replan_count=1,
                unresolved_questions=review.unresolved_questions,
            )
        elif not review.evidence_sufficient:
            state = state.model_copy(
                update={
                    "unresolved_questions": review.unresolved_questions,
                    "limitations": tuple(
                        dict.fromkeys(
                            (
                                *state.limitations,
                                "replan_disabled_for_ablation"
                                if review.replan is not None
                                else "evidence_review_incomplete",
                            )
                        )
                    ),
                }
            )

        draft = self._agent.synthesize(
            observation,
            state,
            tuple(evidence_bundles),
        )
        return LoopResult(
            state=state,
            evidence=tuple(evidence_bundles),
            draft=draft,
        )

    def _validate(self, plan, package, access_scope):
        try:
            return self._plan_validator.validate(plan, package, access_scope)
        except PlanValidationError as exc:
            raise AnalysisLoopError(exc.code, str(exc)) from exc

    def _updated_state(
        self,
        state: AnalysisState,
        evidence: EvidenceBundle,
        *,
        question_ids: tuple[str, ...],
        cycle_count: int,
        replan_count: int,
        unresolved_questions: tuple[str, ...] = (),
    ) -> AnalysisState:
        supported = list(state.supported_predicates)
        rejected = list(state.rejected_predicates)
        inconclusive = list(state.inconclusive_predicates)
        refs = list(state.evidence_refs)
        limitations = list(state.limitations)
        for item in evidence.items:
            refs.append(item.evidence_id)
            limitations.extend(item.limitations)
            for predicate in item.predicates:
                key = ":".join(
                    (predicate.predicate, *predicate.metric_codes)
                )
                if predicate.supported:
                    supported.append(key)
                elif item.analysis_status == "inconclusive":
                    inconclusive.append(key)
                else:
                    rejected.append(key)
        return AnalysisState(
            cycle_count=cycle_count,
            replan_count=replan_count,
            question_ids=tuple(
                dict.fromkeys((*state.question_ids, *question_ids))
            ),
            supported_predicates=tuple(dict.fromkeys(supported)),
            rejected_predicates=tuple(dict.fromkeys(rejected)),
            inconclusive_predicates=tuple(dict.fromkeys(inconclusive)),
            evidence_refs=tuple(dict.fromkeys(refs)),
            unresolved_questions=unresolved_questions,
            limitations=tuple(dict.fromkeys(limitations)),
        )
