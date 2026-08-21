"""Small multilingual ONNX embedding adapter."""

from __future__ import annotations

import numpy as np


MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_VERSION = "paraphrase-multilingual-MiniLM-L12-v2/fastembed-onnx"
EMBEDDING_DIM = 384


class LocalEmbeddingModel:
    def __init__(self, cache_dir: str | None = None):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError("local embeddings require fastembed") from exc
        kwargs = {"model_name": MODEL_NAME}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        self._model = TextEmbedding(**kwargs)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        values = list(self._model.passage_embed(texts))
        return np.asarray(values, dtype=np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        value = next(self._model.query_embed(query))
        return np.asarray(value, dtype=np.float32)
