"""Structure-preserving, deterministic chunking for JATS paragraphs and PDF pages."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

from .models import KnowledgeChunk, KnowledgeSource


CHUNKER_VERSION = "chunker/2.2"
_TRAINING_EVIDENCE_SECTIONS = (
    "abstract",
    "result",
    "discussion",
    "conclusion",
    "key point",
    "practical",
)
_NON_RECOMMENDATION_SECTIONS = ("introduction", "background")


@dataclass(frozen=True)
class TextUnit:
    section: str
    locator: str
    text: str


def estimate_tokens(text: str) -> int:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    non_cjk = re.sub(r"[\u3400-\u9fff\s]", "", text)
    return max(1, cjk + math.ceil(len(non_cjk) / 4))


def _split_long_unit(unit: TextUnit, target_tokens: int) -> list[TextUnit]:
    if estimate_tokens(unit.text) <= target_tokens:
        return [unit]
    sentences = [item.strip() for item in re.split(r"(?<=[.!?。！？])\s+", unit.text) if item.strip()]
    if len(sentences) == 1:
        width = max(200, target_tokens * 4)
        sentences = [unit.text[index : index + width] for index in range(0, len(unit.text), width)]
    parts: list[TextUnit] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in sentences:
        sentence_tokens = estimate_tokens(sentence)
        if current and current_tokens + sentence_tokens > target_tokens:
            parts.append(TextUnit(unit.section, unit.locator, " ".join(current)))
            current = []
            current_tokens = 0
        current.append(sentence)
        current_tokens += sentence_tokens
    if current:
        parts.append(TextUnit(unit.section, unit.locator, " ".join(current)))
    return parts


def chunk_units(
    source: KnowledgeSource,
    units: tuple[TextUnit, ...],
    *,
    target_tokens: int = 350,
    overlap_tokens: int = 60,
    document_id: str | None = None,
    version_id: str = "",
    chunker_version: str = CHUNKER_VERSION,
) -> tuple[KnowledgeChunk, ...]:
    expanded = tuple(
        part
        for unit in units
        for part in _split_long_unit(unit, target_tokens)
        if part.text.strip()
    )
    chunks: list[KnowledgeChunk] = []
    index = 0
    section_ordinals: dict[tuple[str, str], int] = {}
    resolved_document_id = document_id or source.source_id
    while index < len(expanded):
        first = expanded[index]
        selected = [first]
        token_count = estimate_tokens(first.text)
        cursor = index + 1
        while cursor < len(expanded):
            candidate = expanded[cursor]
            if candidate.section != first.section:
                break
            candidate_tokens = estimate_tokens(candidate.text)
            if token_count + candidate_tokens > target_tokens and selected:
                break
            selected.append(candidate)
            token_count += candidate_tokens
            cursor += 1
        text = "\n".join(item.text.strip() for item in selected)
        locator = selected[0].locator
        if selected[-1].locator != locator:
            locator = f"{locator}–{selected[-1].locator}"
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        for domain in source.domains:
            section_key = (domain, first.section)
            ordinal = section_ordinals.get(section_key, 0)
            section_ordinals[section_key] = ordinal + 1
            normalized_section = re.sub(r"\s+", " ", first.section).strip().casefold()
            logical_position = f"{domain}/{normalized_section}/{ordinal:04d}"
            chunk_key = "\x1f".join(
                (resolved_document_id, chunker_version, logical_position, digest)
            )
            chunk_id = hashlib.sha256(chunk_key.encode("utf-8")).hexdigest()
            support_types = source.support_types
            recommendation_allowed = source.recommendation_allowed
            if recommendation_allowed and any(
                normalized_section.startswith(marker)
                for marker in _NON_RECOMMENDATION_SECTIONS
            ):
                recommendation_allowed = False
            if "training_direction" in support_types and not any(
                marker in normalized_section
                for marker in _TRAINING_EVIDENCE_SECTIONS
            ):
                support_types = tuple(
                    item for item in support_types if item != "training_direction"
                )
                recommendation_allowed = False
            chunks.append(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    source_id=source.source_id,
                    document_id=resolved_document_id,
                    version_id=version_id,
                    domain=domain,
                    section=first.section,
                    locator=locator,
                    logical_position=logical_position,
                    text=text,
                    content_digest=digest,
                    token_count=estimate_tokens(text),
                    metric_codes=source.metric_codes,
                    populations=source.populations,
                    support_types=support_types,
                    recommendation_allowed=recommendation_allowed,
                    metadata=source.metadata,
                )
            )
        if cursor >= len(expanded):
            break
        overlap = 0
        next_index = cursor
        while next_index > index + 1 and overlap < overlap_tokens:
            next_index -= 1
            overlap += estimate_tokens(expanded[next_index].text)
        index = next_index if next_index > index else cursor
    return tuple(chunks)
