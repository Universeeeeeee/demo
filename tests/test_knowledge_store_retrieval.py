import json

import numpy as np

from knowledge.models import KnowledgeChunk, SearchRequest
from knowledge.retrieval import HybridRetriever, expand_query
from knowledge.store import KnowledgeStore


class _FakeEmbedder:
    def embed_passages(self, texts):
        vectors = []
        for text in texts:
            vectors.append([1.0, 0.0] if "jump" in text else [0.0, 1.0])
        return np.asarray(vectors, dtype=np.float32)

    def embed_query(self, query):
        return np.asarray([1.0, 0.0] if "jump" in query else [0.0, 1.0], dtype=np.float32)


def _write_chunks(path):
    chunks = (
        KnowledgeChunk(
            chunk_id="jump-1",
            source_id="pmc5377563",
            domain="jump",
            section="Methods",
            locator="Methods ¶1",
            text="vertical jump flight time method",
            content_digest="1" * 64,
            token_count=5,
        ),
        KnowledgeChunk(
            chunk_id="walk-1",
            source_id="pmc4106927",
            domain="walk",
            section="Methods",
            locator="Methods ¶1",
            text="walking gait validity step length",
            content_digest="2" * 64,
            token_count=5,
        ),
    )
    (path / "chunks.jsonl").write_text(
        "\n".join(chunk.model_dump_json() for chunk in chunks) + "\n",
        encoding="utf-8",
    )


def test_store_and_hybrid_retrieval_work_without_vector_database(tmp_path):
    _write_chunks(tmp_path)
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    assert store.build(_FakeEmbedder()) == 2
    retriever = HybridRetriever(store, _FakeEmbedder())

    hits = retriever.search(
        SearchRequest(query="jump flight time", max_results=2),
        domain="jump",
    )

    assert hits[0].chunk.chunk_id == "jump-1"
    assert hits[0].source.source_id == "pmc5377563"
    assert hits[0].dense_rank == 1


def test_query_expansion_reuses_project_metric_language():
    expanded = expand_query("纵跳的跳跃高度和腾空时间")
    assert "vertical jump height" in expanded
    assert "flight time" in expanded
    assert "systematic bias" in expand_query("测量误差来源")
