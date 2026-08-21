"""Versioned Report Agent prompt resources."""

import hashlib
from pathlib import Path


PROMPT_VERSION = "report-agent-system/2.0"
SEQUENTIAL_PROMPT_VERSION = "report-agent-sequential-system/3.0"

DECISION_STAGE_TEMPLATE = (
    "阶段：Sequential Decision。基于最新状态只选择下一项动作或正常停止。"
)
PLAN_STAGE_TEMPLATE = (
    "阶段：Initial Observation。请提出最多3个值得确定性验证的问题和小型计划。"
)
REVIEW_STAGE_TEMPLATE = (
    "阶段：Evidence Review。判断证据是否足够；只有冲突、质量限制或明确未解决问题时才给出一次Replan。"
)
SYNTHESIS_STAGE_TEMPLATE = (
    "阶段：Structured Synthesis。只生成绑定Fact/Evidence的Claim。"
    "Claim文本中的数值必须使用NumericBinding占位符。"
)
SEQUENTIAL_SYNTHESIS_STAGE_TEMPLATE = (
    "阶段：Sequential Structured Synthesis。只生成绑定Fact/Evidence的Claim。"
    "Claim文本中的数值必须使用NumericBinding占位符。"
)
REPAIR_STAGE_TEMPLATE = (
    "阶段：Structured Output Repair。确定性Validator拒绝了Draft。"
    "只修正引用、Claim类型、PredicateBinding或NumericBinding；"
    "不得增加新发现、数值或Evidence。"
)


def load_system_prompt() -> str:
    return (Path(__file__).resolve().parent / "system.md").read_text(
        encoding="utf-8"
    ).strip()


def load_sequential_system_prompt() -> str:
    return (Path(__file__).resolve().parent / "sequential_system.md").read_text(
        encoding="utf-8"
    ).strip()


def prompt_content_digest(*components: str) -> str:
    payload = "\x1f".join(component.strip() for component in components)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def readable_prompt_version(base_version: str, digest: str) -> str:
    return f"{base_version}#{digest[:12]}"
