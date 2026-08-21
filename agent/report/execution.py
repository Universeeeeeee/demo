"""Typed validation and execution boundary for one sequential analysis action."""

from __future__ import annotations

from reporting.models import (
    ActionRejected,
    DataAccessScope,
    EvidenceProduced,
    NextAnalysisAction,
    ReportDataPackage,
    ToolExecutionFailed,
    ValidatedAnalysisAction,
)
from reporting.validators import ActionValidationError, ActionValidator

from .tools import AnalysisToolGateway, TransientAnalysisToolError


MAX_ACTION_CORRECTIONS = 2
MAX_TRANSIENT_TOOL_RETRIES = 1


class SequentialActionBoundary:
    def __init__(
        self,
        *,
        action_validator: ActionValidator | None = None,
        tool_gateway: AnalysisToolGateway | None = None,
        max_transient_retries: int = MAX_TRANSIENT_TOOL_RETRIES,
    ):
        if max_transient_retries < 0:
            raise ValueError("max_transient_retries must be non-negative")
        self._action_validator = action_validator or ActionValidator()
        self._tool_gateway = tool_gateway or AnalysisToolGateway()
        self._max_transient_retries = max_transient_retries

    def validate(
        self,
        action: NextAnalysisAction,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
        *,
        seen_request_hashes: frozenset[str] = frozenset(),
        seen_action_ids: frozenset[str] = frozenset(),
        seen_hypothesis_ids: frozenset[str] = frozenset(),
        remaining_tool_calls: int = 1,
        action_correction_count: int = 0,
    ) -> ValidatedAnalysisAction | ActionRejected:
        try:
            return self._action_validator.validate_action(
                action,
                package,
                access_scope,
                seen_request_hashes=seen_request_hashes,
                seen_action_ids=seen_action_ids,
                seen_hypothesis_ids=seen_hypothesis_ids,
                remaining_tool_calls=remaining_tool_calls,
            )
        except ActionValidationError as exc:
            return ActionRejected(
                action=action,
                error_code=exc.code,
                message=str(exc),
                correction_allowed=(
                    action_correction_count < MAX_ACTION_CORRECTIONS
                ),
            )

    def execute(
        self,
        action: ValidatedAnalysisAction,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
    ) -> EvidenceProduced | ToolExecutionFailed:
        attempt_count = 0
        while True:
            attempt_count += 1
            try:
                evidence = self._tool_gateway.execute_action(
                    package,
                    action,
                    access_scope,
                )
                return EvidenceProduced(
                    action=action,
                    evidence=evidence,
                    attempt_count=attempt_count,
                )
            except TransientAnalysisToolError as exc:
                if attempt_count <= self._max_transient_retries:
                    continue
                return ToolExecutionFailed(
                    action=action,
                    error_code=getattr(exc, "code", "transient_tool_failure"),
                    message=str(exc) or type(exc).__name__,
                    failure_kind="transient",
                    attempt_count=attempt_count,
                    retry_exhausted=True,
                )
            except Exception as exc:
                return ToolExecutionFailed(
                    action=action,
                    error_code=getattr(exc, "code", "tool_execution_failed"),
                    message=str(exc) or type(exc).__name__,
                    failure_kind="hard",
                    attempt_count=attempt_count,
                    retry_exhausted=False,
                )


__all__ = [
    "MAX_ACTION_CORRECTIONS",
    "MAX_TRANSIENT_TOOL_RETRIES",
    "SequentialActionBoundary",
]
