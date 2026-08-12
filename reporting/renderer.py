"""Deterministic injection of validated numeric evidence into final claims."""

from __future__ import annotations

from .models import (
    AnalysisClaim,
    AnalysisPackage,
    AnalysisState,
    DataAccessScope,
    ReportDataPackage,
    ValidatedAnalysisPackage,
)


class AnalysisRenderer:
    def render(
        self,
        validated: ValidatedAnalysisPackage,
        *,
        analysis_run_id: str,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
        state: AnalysisState,
        model_name: str,
        prompt_version: str,
    ) -> AnalysisPackage:
        claims = []
        for claim in validated.claims:
            text = claim.text_template
            for binding in claim.numeric_bindings:
                text = text.replace(
                    "{" + binding.binding_id + "}",
                    self._format_value(binding.value, binding.unit),
                )
            claims.append(
                AnalysisClaim(
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    text=text,
                    fact_refs=claim.fact_refs,
                    evidence_refs=claim.evidence_refs,
                    tool_run_ids=claim.tool_run_ids,
                    predicate_bindings=claim.predicate_bindings,
                    limitations=claim.limitations,
                )
            )
        return AnalysisPackage(
            analysis_schema_version="analysis-schema/3.0",
            analysis_run_id=analysis_run_id,
            session_id=package.metadata.session_id,
            package_id=package.metadata.package_id,
            package_digest=package.metadata.package_digest,
            data_access_scope=access_scope,
            summary=validated.summary,
            claims=tuple(claims),
            scope_expansion_suggestions=validated.scope_expansion_suggestions,
            overall_limitations=validated.overall_limitations,
            cycle_count=getattr(
                state, "cycle_count", getattr(state, "tool_call_count", 0)
            ),
            replan_count=getattr(state, "replan_count", 0),
            model_name=model_name,
            prompt_version=prompt_version,
        )

    def _format_value(self, value: float, unit: str) -> str:
        if value.is_integer():
            number = str(int(value))
        else:
            number = f"{value:.3f}".rstrip("0").rstrip(".")
        return f"{number} {unit}"
