"""Report Agent schemas; deterministic plan contracts live in reporting."""

from pydantic import BaseModel, ConfigDict, Field

from reporting.models import (
    ActionRejected,
    AnalysisNode,
    AnalysisQuestion,
    DraftAnalysisPackage,
    EvidenceReviewDecision,
    EvidenceProduced,
    HypothesisTarget,
    InvestigationDecision,
    HypothesisEvaluation,
    LoadSkillResource,
    NextAnalysisAction,
    AnalysisState,
    AnalysisDecision,
    DataAccessScope,
    SmallAnalysisPlan,
    SequentialAnalysisState,
    StopAnalysis,
    ToolExecutionFailed,
)


class ReportAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: int = Field(gt=0)
    data_access_scope: DataAccessScope

__all__ = [
    "ActionRejected",
    "AnalysisNode",
    "AnalysisQuestion",
    "AnalysisState",
    "AnalysisDecision",
    "DraftAnalysisPackage",
    "EvidenceReviewDecision",
    "EvidenceProduced",
    "HypothesisTarget",
    "InvestigationDecision",
    "HypothesisEvaluation",
    "LoadSkillResource",
    "NextAnalysisAction",
    "ReportAnalysisRequest",
    "SmallAnalysisPlan",
    "SequentialAnalysisState",
    "StopAnalysis",
    "ToolExecutionFailed",
]
