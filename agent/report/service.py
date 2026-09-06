"""Application service coordinating one trusted report-analysis run."""

from __future__ import annotations

import time
from types import SimpleNamespace

from reporting.builders import ReportManifestBuilder
from reporting.kernel import (
    ANALYSIS_METHOD_REGISTRY_VERSION,
    KERNEL_VERSION,
    AnalysisMethodRegistry,
)
from reporting.models import (
    AnalysisPackage,
    AnalysisRunMetrics,
    DataAccessScope,
    DataScopeAvailability,
    SequentialLoopCheckpoint,
    SequentialLoopResult,
)
from reporting.observation import (
    OBSERVATION_BUILDER_VERSION,
    ObservationBuilder,
    estimate_observation_tokens,
    serialize_observation,
)
from reporting.renderer import AnalysisRenderer
from reporting.repository import ReportRepository
from reporting.tools import ANALYSIS_TOOL_REGISTRY_VERSION, AnalysisToolRegistry
from reporting.validators import (
    ActionValidator,
    ClaimRepairValidationError,
    ClaimRepairValidator,
    ClaimValidationError,
    ClaimValidator,
    PlanValidator,
)
from knowledge.integration import build_report_rag_context
from knowledge.pipeline import degraded_rag_result

from .agent import ReportAgent
from .analysis_loop import AnalysisLoop, AnalysisLoopError
from .checkpoint import RepositoryCheckpointSink
from .execution import SequentialActionBoundary
from .sequential_loop import (
    SequentialAnalysisLoop,
    SequentialAnalysisLoopError,
)
from .skill_loader import ReportAnalysisSkillLoader, SkillLoadError
from .tools import AnalysisToolGateway


class ReportAnalysisError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ReportAnalysisService:
    def __init__(
        self,
        repository: ReportRepository,
        *,
        agent=None,
        tool_registry: AnalysisToolRegistry | None = None,
        method_registry: AnalysisMethodRegistry | None = None,
        observation_builder: ObservationBuilder | None = None,
        claim_validator: ClaimValidator | None = None,
        claim_repair_validator: ClaimRepairValidator | None = None,
        renderer: AnalysisRenderer | None = None,
        max_replans: int = 0,
        skill_loader: ReportAnalysisSkillLoader | None = None,
        rag_pipeline=None,
        rag_unavailable_error_code: str | None = None,
    ):
        self._repository = repository
        self._agent = agent or ReportAgent()
        self._tool_registry = tool_registry or AnalysisToolRegistry()
        self._method_registry = method_registry or AnalysisMethodRegistry()
        self._observation_builder = observation_builder or ObservationBuilder(
            include_analysis_sketch=True,
            include_compact_series=True,
            include_screening_cues=False,
        )
        self._claim_validator = claim_validator or ClaimValidator()
        self._claim_repair_validator = (
            claim_repair_validator or ClaimRepairValidator()
        )
        self._renderer = renderer or AnalysisRenderer()
        self._max_replans = max_replans
        self._skill_loader = skill_loader or ReportAnalysisSkillLoader()
        self._rag_pipeline = rag_pipeline
        self._rag_unavailable_error_code = rag_unavailable_error_code

    def analyze(
        self,
        session_id: int,
        access_scope: DataAccessScope,
    ) -> AnalysisPackage:
        if access_scope.longitudinal or access_scope.cohort:
            raise ReportAnalysisError(
                "external_scope_not_implemented",
                "Longitudinal and cohort analysis are not implemented in this MVP",
            )
        package = self._repository.get_package(session_id)
        manifest = ReportManifestBuilder().build(package)
        availability = DataScopeAvailability(
            reasons=("external_scope_not_requested",)
        )
        capabilities = self._tool_registry.list_capabilities(
            package, access_scope, self._method_registry
        )
        observation = self._observation_builder.build(
            package,
            manifest,
            availability,
            access_scope,
            capabilities,
        )
        model_name = getattr(self._agent, "model_name", "unknown")
        use_sequential_loop = callable(getattr(self._agent, "decide", None))
        prompt_version = getattr(
            self._agent,
            "sequential_prompt_version"
            if use_sequential_loop
            else "prompt_version",
            "unknown",
        )
        prompt_content_digest = getattr(
            self._agent,
            "sequential_prompt_content_digest"
            if use_sequential_loop
            else "prompt_content_digest",
            None,
        )
        resume_from = None
        run_id = None
        if use_sequential_loop:
            try:
                skill_context = self._skill_loader.load_initial(
                    package.context.test_type
                )
            except SkillLoadError as exc:
                raise ReportAnalysisError(exc.code, str(exc)) from exc
            resumable = self._repository.get_resumable_analysis_checkpoint(
                session_id,
                access_scope,
                package.metadata.package_digest,
                model_name=model_name,
                prompt_version=prompt_version,
                prompt_content_digest=prompt_content_digest,
                skill_version=skill_context.skill_version,
                observation_builder_version=OBSERVATION_BUILDER_VERSION,
                analysis_tool_registry_version=ANALYSIS_TOOL_REGISTRY_VERSION,
                analysis_method_registry_version=ANALYSIS_METHOD_REGISTRY_VERSION,
                kernel_version=KERNEL_VERSION,
            )
            if resumable is not None and self._checkpoint_skill_matches(
                resumable.checkpoint, package.context.test_type
            ):
                run_id = resumable.analysis_run_id
                resume_from = resumable.checkpoint
        if run_id is None:
            run_id = self._repository.create_analysis_run(
                session_id,
                access_scope,
                package.metadata.package_digest,
                model_name=model_name,
                prompt_version=prompt_version,
            )
        started = time.perf_counter()
        result = None
        checkpoint_sink = None
        claim_repair_count = 0
        try:
            gateway = AnalysisToolGateway(
                tool_registry=self._tool_registry,
                method_registry=self._method_registry,
            )
            if use_sequential_loop:
                checkpoint_sink = RepositoryCheckpointSink(
                    self._repository, run_id
                )
                action_validator = ActionValidator(
                    self._tool_registry, self._method_registry
                )
                loop = SequentialAnalysisLoop(
                    self._agent,
                    skill_loader=self._skill_loader,
                    action_validator=action_validator,
                    action_boundary=SequentialActionBoundary(
                        action_validator=action_validator,
                        tool_gateway=gateway,
                    ),
                    checkpoint_sink=checkpoint_sink,
                    prompt_content_digest=prompt_content_digest,
                )
                if resume_from is not None and resume_from.phase in {
                    "draft_generated",
                    "claim_repair_pending",
                }:
                    result = SequentialLoopResult(
                        state=resume_from.state,
                        evidence=resume_from.evidence,
                        draft=resume_from.draft,
                        skill_version=resume_from.skill_version,
                        skill_content_digest=resume_from.skill_content_digest,
                    )
                    claim_repair_count = resume_from.claim_repair_count
                else:
                    result = loop.run(
                        observation,
                        package,
                        access_scope,
                        resume_from=resume_from,
                    )
                    self._save_claim_checkpoint(
                        checkpoint_sink,
                        "draft_generated",
                        package,
                        access_scope,
                        result,
                        prompt_content_digest=prompt_content_digest,
                    )
            else:
                loop = AnalysisLoop(
                    self._agent,
                    plan_validator=PlanValidator(
                        self._tool_registry, self._method_registry
                    ),
                    tool_gateway=gateway,
                    max_replans=self._max_replans,
                )
                result = loop.run(observation, package, access_scope)
            try:
                validated = self._claim_validator.validate(
                    result.draft,
                    package,
                    result.evidence,
                    access_scope,
                )
            except ClaimValidationError as first_error:
                repair = getattr(self._agent, "repair_synthesis", None)
                if (
                    not callable(repair)
                    or claim_repair_count >= 1
                    or not self._claim_repair_validator.can_repair(
                        first_error.code
                    )
                ):
                    raise
                if use_sequential_loop:
                    self._save_claim_checkpoint(
                        checkpoint_sink,
                        "claim_repair_pending",
                        package,
                        access_scope,
                        result,
                        error_code=first_error.code,
                        error_message=str(first_error),
                        claim_repair_count=claim_repair_count,
                        prompt_content_digest=prompt_content_digest,
                    )
                repaired_draft = repair(
                    observation,
                    result.state,
                    result.evidence,
                    result.draft,
                    first_error.code,
                    str(first_error),
                )
                try:
                    self._claim_repair_validator.validate(
                        result.draft,
                        repaired_draft,
                        first_error.code,
                        package,
                        result.evidence,
                    )
                except ClaimRepairValidationError as repair_error:
                    raise ClaimValidationError(
                        repair_error.code, str(repair_error)
                    ) from repair_error
                claim_repair_count += 1
                result = result.model_copy(update={"draft": repaired_draft})
                if use_sequential_loop:
                    self._save_claim_checkpoint(
                        checkpoint_sink,
                        "draft_generated",
                        package,
                        access_scope,
                        result,
                        claim_repair_count=claim_repair_count,
                        prompt_content_digest=prompt_content_digest,
                    )
                validated = self._claim_validator.validate(
                    repaired_draft,
                    package,
                    result.evidence,
                    access_scope,
                )
            rag_result = None
            if self._rag_pipeline is not None:
                try:
                    rag_context = build_report_rag_context(
                        package, validated, result.evidence
                    )
                    rag_result = self._rag_pipeline.run(rag_context)
                except Exception:
                    rag_result = degraded_rag_result(
                        package.metadata.package_digest,
                        "rag_integration_failed",
                    )
            elif self._rag_unavailable_error_code is not None:
                rag_result = degraded_rag_result(
                    package.metadata.package_digest,
                    self._rag_unavailable_error_code,
                )
            rendered = self._renderer.render(
                validated,
                analysis_run_id=run_id,
                package=package,
                access_scope=access_scope,
                state=result.state,
                model_name=model_name,
                prompt_version=prompt_version,
                prompt_content_digest=prompt_content_digest,
                rag_result=rag_result,
            )
            self._record_metrics(
                run_id,
                package.metadata.package_digest,
                observation,
                model_name,
                prompt_version,
                prompt_content_digest,
                started,
                result,
            )
            self._repository.finalize_analysis_run(
                run_id,
                "validated",
                rendered.model_dump(mode="json"),
            )
            return rendered
        except (
            AnalysisLoopError,
            SequentialAnalysisLoopError,
            ClaimValidationError,
        ) as exc:
            metrics_result = self._metrics_result(
                result, exc, checkpoint_sink
            )
            self._record_metrics(
                run_id,
                package.metadata.package_digest,
                observation,
                model_name,
                prompt_version,
                prompt_content_digest,
                started,
                metrics_result,
            )
            self._repository.finalize_analysis_run(
                run_id,
                "rejected",
                None,
                exc.code,
            )
            raise ReportAnalysisError(exc.code, str(exc)) from exc
        except Exception as exc:
            metrics_result = self._metrics_result(
                result, exc, checkpoint_sink
            )
            self._safe_record_metrics(
                run_id,
                package.metadata.package_digest,
                observation,
                model_name,
                prompt_version,
                prompt_content_digest,
                started,
                metrics_result,
            )
            self._repository.finalize_analysis_run(
                run_id,
                "failed",
                None,
                "analysis_failed",
            )
            raise ReportAnalysisError("analysis_failed", str(exc)) from exc

    def _save_claim_checkpoint(
        self,
        checkpoint_sink,
        phase,
        package,
        access_scope,
        result,
        *,
        error_code=None,
        error_message=None,
        claim_repair_count=0,
        prompt_content_digest=None,
    ) -> None:
        checkpoint_sink.save(
            SequentialLoopCheckpoint(
                phase=phase,
                session_id=package.metadata.session_id,
                package_digest=package.metadata.package_digest,
                data_access_scope=access_scope,
                state=result.state,
                evidence=result.evidence,
                draft=result.draft,
                claim_validation_error_code=error_code,
                claim_validation_error_message=error_message,
                claim_repair_count=claim_repair_count,
                skill_version=result.skill_version,
                skill_content_digest=result.skill_content_digest,
                observation_builder_version=OBSERVATION_BUILDER_VERSION,
                analysis_tool_registry_version=ANALYSIS_TOOL_REGISTRY_VERSION,
                analysis_method_registry_version=ANALYSIS_METHOD_REGISTRY_VERSION,
                kernel_version=KERNEL_VERSION,
                prompt_content_digest=prompt_content_digest,
            )
        )

    def _metrics_result(self, result, exc, checkpoint_sink):
        if result is not None:
            return result
        checkpoint = (
            checkpoint_sink.latest_checkpoint
            if checkpoint_sink is not None
            else None
        )
        state = getattr(exc, "state", None)
        if state is None and checkpoint is not None:
            state = checkpoint.state
        if state is None:
            return None
        evidence = getattr(exc, "evidence", ())
        if checkpoint is not None and len(checkpoint.evidence) > len(evidence):
            evidence = checkpoint.evidence
        return SimpleNamespace(state=state, evidence=evidence)

    def _checkpoint_skill_matches(self, checkpoint, test_type) -> bool:
        try:
            context = self._skill_loader.load_initial(test_type)
            for reference_id in checkpoint.state.loaded_skill_references:
                if reference_id not in context.loaded_reference_ids:
                    context = self._skill_loader.load_reference(
                        context, reference_id
                    )
        except SkillLoadError:
            return False
        return (
            context.skill_version == checkpoint.skill_version
            and context.content_digest == checkpoint.skill_content_digest
        )

    def get_latest(
        self,
        session_id: int,
        access_scope: DataAccessScope,
    ) -> dict | None:
        package = self._repository.get_package(session_id)
        return self._repository.get_latest_validated_analysis(
            session_id,
            access_scope,
            package.metadata.package_digest,
        )

    def _record_metrics(
        self,
        run_id,
        package_digest,
        observation,
        model_name,
        prompt_version,
        prompt_content_digest,
        started,
        result,
    ):
        serialized = serialize_observation(observation)
        evidence = result.evidence if result is not None else ()
        self._repository.update_analysis_run_metrics(
            run_id,
            AnalysisRunMetrics(
                model_name=model_name,
                prompt_version=prompt_version,
                prompt_content_digest=prompt_content_digest,
                observation_builder_version=OBSERVATION_BUILDER_VERSION,
                analysis_tool_registry_version=ANALYSIS_TOOL_REGISTRY_VERSION,
                analysis_method_registry_version=ANALYSIS_METHOD_REGISTRY_VERSION,
                kernel_version=KERNEL_VERSION,
                package_digest=package_digest,
                cycle_count=(
                    getattr(
                        result.state,
                        "cycle_count",
                        getattr(result.state, "tool_call_count", 0),
                    )
                    if result is not None
                    else 0
                ),
                replan_count=(
                    getattr(result.state, "replan_count", 0)
                    if result is not None
                    else 0
                ),
                agent_level_node_count=sum(len(bundle.items) for bundle in evidence),
                tool_run_count=sum(len(bundle.tool_runs) for bundle in evidence),
                duplicate_request_count=0,
                observation_size=len(serialized.encode("utf-8")),
                estimated_tokens=estimate_observation_tokens(serialized),
                elapsed_ms=max(0, round((time.perf_counter() - started) * 1000)),
            ),
        )

    def _safe_record_metrics(self, *args) -> None:
        try:
            self._record_metrics(*args)
        except Exception:
            # The original failure remains authoritative; the run is still finalized.
            pass
