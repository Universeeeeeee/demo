"""Load and validate the tracked authoritative-source catalog."""

from __future__ import annotations

import json
from pathlib import Path

from .models import KnowledgeSource


DEFAULT_CATALOG_PATH = Path(__file__).with_name("sources.json")


def load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> tuple[KnowledgeSource, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    sources = tuple(KnowledgeSource.model_validate(item) for item in payload["sources"])
    ids = [source.source_id for source in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("knowledge source IDs must be unique")
    for source in sources:
        if source.ingest_policy == "full_text" and source.download_url is None:
            raise ValueError(f"full-text source lacks download URL: {source.source_id}")
        if source.ingest_policy == "metadata_only" and source.source_format != "metadata":
            raise ValueError(f"metadata-only source has ingestible format: {source.source_id}")
    return sources
