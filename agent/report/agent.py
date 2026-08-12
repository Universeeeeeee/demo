"""PydanticAI implementation of the single logical Report Agent."""

from __future__ import annotations

import asyncio
import json

import httpx
from pydantic_ai import Agent

from agent.common.model_provider import build_chat_model, default_model_settings
from reporting.models import (
    AnalysisDecision,
    AgentObservation,
    AnalysisState,
    DraftAnalysisPackage,
    EvidenceBundle,
    EvidenceReviewDecision,
    InvestigationDecision,
    SequentialAnalysisState,
)
from reporting.observation import serialize_observation

from .prompts import (
    PROMPT_VERSION,
    SEQUENTIAL_PROMPT_VERSION,
    load_sequential_system_prompt,
    load_system_prompt,
)
from .skill_loader import ReportAnalysisSkillContext


class ReportAgent:
    model_name = "deepseek-v4-flash"
    prompt_version = PROMPT_VERSION
    sequential_prompt_version = SEQUENTIAL_PROMPT_VERSION

    def __init__(self):
        self._system_prompt = load_system_prompt()
        self._sequential_system_prompt = load_sequential_system_prompt()

    def decide(
        self,
        observation: AgentObservation,
        state: SequentialAnalysisState,
        evidence: tuple[EvidenceBundle, ...],
        skill_context: ReportAnalysisSkillContext,
    ) -> AnalysisDecision:
        prompt = (
            "阶段：Sequential Decision。基于最新状态只选择下一项动作或正常停止。\n"
            f"Report Analysis Skill:\n{skill_context.instructions}\n"
            f"Observation:\n{serialize_observation(observation)}\n"
            f"State:\n{self._json(state)}\n"
            f"Evidence:\n{self._json(evidence)}"
        )
        return self._run(
            AnalysisDecision,
            prompt,
            instructions=self._sequential_system_prompt,
        )

    def propose_plan(
        self,
        observation: AgentObservation,
        state: AnalysisState,
    ) -> InvestigationDecision:
        prompt = (
            "阶段：Initial Observation。请提出最多3个值得确定性验证的问题和小型计划。\n"
            f"Observation:\n{serialize_observation(observation)}\n"
            f"State:\n{self._json(state)}"
        )
        return self._run(InvestigationDecision, prompt)

    def review_evidence(
        self,
        observation: AgentObservation,
        state: AnalysisState,
        evidence: tuple[EvidenceBundle, ...],
    ) -> EvidenceReviewDecision:
        prompt = (
            "阶段：Evidence Review。判断证据是否足够；只有冲突、质量限制或明确未解决问题时才给出一次Replan。\n"
            f"Observation:\n{serialize_observation(observation)}\n"
            f"State:\n{self._json(state)}\n"
            f"Evidence:\n{self._json(evidence)}"
        )
        return self._run(EvidenceReviewDecision, prompt)

    def synthesize(
        self,
        observation: AgentObservation,
        state: AnalysisState,
        evidence: tuple[EvidenceBundle, ...],
    ) -> DraftAnalysisPackage:
        prompt = (
            "阶段：Structured Synthesis。只生成绑定Fact/Evidence的Claim。Claim文本中的数值必须使用NumericBinding占位符。\n"
            f"Observation:\n{serialize_observation(observation)}\n"
            f"State:\n{self._json(state)}\n"
            f"Evidence:\n{self._json(evidence)}"
        )
        return self._run(DraftAnalysisPackage, prompt)

    def synthesize_sequential(
        self,
        observation: AgentObservation,
        state: SequentialAnalysisState,
        evidence: tuple[EvidenceBundle, ...],
        skill_context: ReportAnalysisSkillContext,
    ) -> DraftAnalysisPackage:
        prompt = (
            "阶段：Sequential Structured Synthesis。只生成绑定Fact/Evidence的Claim。"
            "Claim文本中的数值必须使用NumericBinding占位符。\n"
            f"Report Analysis Skill:\n{skill_context.instructions}\n"
            f"Observation:\n{serialize_observation(observation)}\n"
            f"State:\n{self._json(state)}\n"
            f"Evidence:\n{self._json(evidence)}"
        )
        return self._run(DraftAnalysisPackage, prompt)

    def repair_synthesis(
        self,
        observation: AgentObservation,
        state: AnalysisState,
        evidence: tuple[EvidenceBundle, ...],
        draft: DraftAnalysisPackage,
        error_code: str,
        error_message: str,
    ) -> DraftAnalysisPackage:
        prompt = (
            "阶段：Structured Output Repair。确定性Validator拒绝了Draft。"
            "只修正引用、Claim类型、PredicateBinding或NumericBinding；"
            "不得增加新发现、数值或Evidence。\n"
            f"Validation error: {error_code}: {error_message}\n"
            f"Observation:\n{serialize_observation(observation)}\n"
            f"State:\n{self._json(state)}\n"
            f"Evidence:\n{self._json(evidence)}\n"
            f"Rejected Draft:\n{self._json(draft)}"
        )
        return self._run(DraftAnalysisPackage, prompt)

    def _run(self, output_type, prompt, *, instructions=None):
        async def flow():
            client = httpx.AsyncClient()
            try:
                runtime_agent = Agent(
                    model=build_chat_model(client),
                    output_type=output_type,
                    instructions=instructions or self._system_prompt,
                    retries=1,
                    model_settings=default_model_settings(),
                )
                result = await runtime_agent.run(prompt)
                return result.output
            finally:
                await client.aclose()

        return asyncio.run(flow())

    def _json(self, value) -> str:
        if isinstance(value, tuple):
            value = [item.model_dump(mode="json") for item in value]
        else:
            value = value.model_dump(mode="json")
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
