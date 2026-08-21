"""Deterministic source formatting and reference rendering."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from .models import (
    Citation,
    CitationBinding,
    KnowledgeSource,
    LiteratureEvidence,
    RetrievalHit,
    SearchResult,
    SearchSource,
)


_CITE_INSTRUCTION = "Cite the relevant URLs above as markdown links in your answer."


def _markdown_label(value: str) -> str:
    return re.sub(r"([\\\[\]])", r"\\\1", value.replace("\n", " ").strip())


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def _source_label(source: SearchSource) -> str:
    if source.title and source.title.strip():
        return source.title.strip()
    return urlsplit(source.url).hostname or source.url


def format_search_output(result: SearchResult) -> str:
    """Format one search result for an Agent, matching the Harness convention."""
    parts: list[str] = []
    if result.content:
        parts.append(result.content)
    if result.sources:
        lines = []
        for source in result.sources:
            meta = []
            if source.snippet:
                meta.append(source.snippet.replace("\n", " ").strip())
            if source.published_at:
                meta.append(f"({source.published_at})")
            suffix = f" — {' '.join(meta)}" if meta else ""
            lines.append(
                f"- [{_markdown_label(_source_label(source))}]({source.url}){suffix}"
            )
        parts.append("Sources:\n" + "\n".join(lines))
    elif not result.content:
        parts.append("No results found.")
    if result.truncated:
        parts.append(
            f"(Showing the first {len(result.sources)} sources. Refine the query for more.)"
        )
    parts.append(_CITE_INSTRUCTION)
    return "\n\n".join(parts)


def render_cited_answer(
    answer_markdown: str,
    bindings: tuple[CitationBinding, ...],
    hits: tuple[RetrievalHit, ...],
) -> str:
    """Resolve selected chunk bindings and append a deterministic reference list."""
    hit_by_chunk = {hit.chunk.chunk_id: hit for hit in hits}
    ordered: list[RetrievalHit] = []
    seen_urls: set[str] = set()
    for binding in bindings:
        hit = hit_by_chunk.get(binding.chunk_id)
        if hit is None:
            raise ValueError(f"citation binding cannot resolve chunk: {binding.chunk_id}")
        key = _canonical_url(hit.source.url)
        if key in seen_urls:
            continue
        seen_urls.add(key)
        ordered.append(hit)

    body = answer_markdown.strip()
    if not ordered:
        return body
    lines = ["## 参考资料"]
    for hit in ordered:
        label = _markdown_label(hit.source.title)
        details = []
        if hit.source.authors:
            details.append(", ".join(hit.source.authors[:3]))
        if hit.source.year:
            details.append(str(hit.source.year))
        details.append(hit.chunk.locator)
        suffix = " — " + "；".join(details) if details else ""
        lines.append(f"- [{label}]({hit.source.url}){suffix}")
    return body + "\n\n" + "\n".join(lines)


def build_citations(
    evidence: tuple[LiteratureEvidence, ...],
    sources: tuple[KnowledgeSource, ...],
) -> tuple[Citation, ...]:
    """Create one deterministic, resolvable citation for each Evidence item."""
    source_by_id = {source.source_id: source for source in sources}
    citations = []
    seen_ids = set()
    for item in evidence:
        try:
            source = source_by_id[item.source_id]
        except KeyError as exc:
            raise ValueError(f"citation source cannot resolve: {item.source_id}") from exc
        citation_id = "cite-" + hashlib.sha256(
            f"{item.evidence_id}\x1f{item.chunk_id}\x1f{source.url}".encode("utf-8")
        ).hexdigest()[:16]
        if citation_id in seen_ids:
            raise ValueError(f"duplicate citation ID: {citation_id}")
        seen_ids.add(citation_id)
        citations.append(
            Citation(
                citation_id=citation_id,
                evidence_id=item.evidence_id,
                source_id=source.source_id,
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                title=source.title,
                url=source.url,
                doi=source.doi,
                locator=item.locator,
            )
        )
    return tuple(citations)


def render_references_markdown(citations: tuple[Citation, ...]) -> str:
    if not citations:
        return ""
    lines = ["## 参考资料"]
    for citation in citations:
        details = [citation.locator] if citation.locator else []
        if citation.doi:
            details.append(f"DOI: {citation.doi}")
        suffix = " — " + "；".join(details) if details else ""
        lines.append(
            f"- [{_markdown_label(citation.title)}]({citation.url}){suffix}"
        )
    return "\n".join(lines)
