"""One-time chunk-size selection for the initial core corpus."""

from __future__ import annotations

import json

from .embeddings import LocalEmbeddingModel
from .evaluation import evaluate
from .ingestion import DEFAULT_DATA_DIR, build_chunk_snapshot
from .retrieval import HybridRetriever
from .store import DEFAULT_DB_PATH, KnowledgeStore


CHUNK_GRID = ((220, 40), (350, 60), (500, 80))


def benchmark_chunk_grid() -> dict:
    embedder = LocalEmbeddingModel()
    results = []
    for target_tokens, overlap_tokens in CHUNK_GRID:
        chunks = build_chunk_snapshot(
            target_tokens=target_tokens,
            overlap_tokens=overlap_tokens,
        )
        store = KnowledgeStore(
            DEFAULT_DATA_DIR / f"knowledge-{target_tokens}.sqlite3"
        )
        store.build(embedder)
        metrics = evaluate(HybridRetriever(store, embedder))
        results.append(
            {
                "target_tokens": target_tokens,
                "overlap_tokens": overlap_tokens,
                "chunk_count": len(chunks),
                "average_chunk_tokens": sum(chunk.token_count for chunk in chunks) / len(chunks),
                "locator_coverage": sum(bool(chunk.locator) for chunk in chunks) / len(chunks),
                "recall_at_5": metrics["recall_at_5"],
                "recall_at_10": metrics["recall_at_10"],
                "mrr": metrics["mrr"],
                "ndcg_at_10": metrics["ndcg_at_10"],
                "domain_recall_at_10": metrics["domain_recall_at_10"],
            }
        )
    selected = max(
        results,
        key=lambda item: (
            item["locator_coverage"],
            item["recall_at_10"],
            item["ndcg_at_10"],
            -item["average_chunk_tokens"],
            -item["target_tokens"],
        ),
    )
    build_chunk_snapshot(
        target_tokens=selected["target_tokens"],
        overlap_tokens=selected["overlap_tokens"],
    )
    KnowledgeStore(DEFAULT_DB_PATH).build(embedder)
    payload = {
        "benchmark_version": "chunk-grid/0.1",
        "results": results,
        "selected": selected,
    }
    (DEFAULT_DATA_DIR / "chunk_grid_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload
