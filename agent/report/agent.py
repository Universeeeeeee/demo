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
    DECISION_STAGE_TEMPLATE,
    PLAN_STAGE_TEMPLATE,
    PROMPT_VERSION,
    REPAIR_STAGE_TEMPLATE,
    REVIEW_STAGE_TEMPLATE,
    SEQUENTIAL_PROMPT_VERSION,
    SEQUENTIAL_SYNTHESIS_STAGE_TEMPLATE,
    SYNTHESIS_STAGE_TEMPLATE,
    load_sequential_system_prompt,
    load_system_prompt,
    prompt_content_digest,
    readable_prompt_version,
)
from .skill_loader import ReportAnalysisSkillContext


class ReportAgent:
    model_name = "deepseek-v4-flash"
    prompt_version = PROMPT_VERSION
    sequential_prompt_version = SEQUENTIAL_PROMPT_VERSION

    def __init__(self):
        self._system_prompt = load_system_prompt()
        self._sequential_system_prompt = load_sequential_system_prompt()
        self.prompt_content_digest = prompt_content_digest(
            self._system_prompt,
            PLAN_STAGE_TEMPLATE,
            REVIEW_STAGE_TEMPLATE,
            SYNTHESIS_STAGE_TEMPLATE,
            REPAIR_STAGE_TEMPLATE,
        )
        self.sequential_prompt_content_digest = prompt_content_digest(
            self._sequential_system_prompt,
            self._system_prompt,
            DECISION_STAGE_TEMPLATE,
            SEQUENTIAL_SYNTHESIS_STAGE_TEMPLATE,
            REPAIR_STAGE_TEMPLATE,
        )
        self.prompt_version = readable_prompt_version(
            PROMPT_VERSION, self.prompt_content_digest
        )
        self.sequential_prompt_version = readable_prompt_version(
            SEQUENTIAL_PROMPT_VERSION,
            self.sequential_prompt_content_digest,
        )

    def decide(
        self,
        observation: AgentObservation,
        state: SequentialAnalysisState,
        evidence: tuple[EvidenceBundle, ...],
        skill_context: ReportAnalysisSkillContext,
    ) -> AnalysisDecision:
        prompt = (
            f"{DECISION_STAGE_TEMPLATE}\n"
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
            f"{PLAN_STAGE_TEMPLATE}\n"
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
            f"{REVIEW_STAGE_TEMPLATE}\n"
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
            f"{SYNTHESIS_STAGE_TEMPLATE}\n"
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
            f"{SEQUENTIAL_SYNTHESIS_STAGE_TEMPLATE}\n"
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
            f"{REPAIR_STAGE_TEMPLATE}\n"
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
