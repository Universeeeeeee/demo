"""Local authoritative knowledge retrieval for sports-test explanations."""

from .citations import (
    build_citations,
    format_search_output,
    render_cited_answer,
    render_references_markdown,
)
from .models import (
    Citation,
    CitationBinding,
    DocumentVersion,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeQuerySpec,
    KnowledgeSource,
    LiteratureEvidence,
    RAGAudit,
    RAGResult,
    Recommendation,
    RetrievalHit,
    SearchRequest,
    SearchResult,
    SearchSource,
    ValidatedRecommendationPackage,
)

__all__ = [
    "Citation",
    "CitationBinding",
    "DocumentVersion",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeQuerySpec",
    "KnowledgeSource",
    "LiteratureEvidence",
    "RAGAudit",
    "RAGResult",
    "Recommendation",
    "RetrievalHit",
    "SearchRequest",
    "SearchResult",
    "SearchSource",
    "ValidatedRecommendationPackage",
    "build_citations",
    "format_search_output",
    "render_cited_answer",
    "render_references_markdown",
]
