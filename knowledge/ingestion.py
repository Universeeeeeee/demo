"""Download, parse, and snapshot the allowlisted core sports corpus."""

from __future__ import annotations

import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from .catalog import load_catalog
from .chunking import CHUNKER_VERSION, TextUnit, chunk_units
from .models import KnowledgeChunk


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "knowledge"
CORPUS_VERSION = "sports-rag-corpus/1.4"


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _element_text(element: ET.Element) -> str:
    return _clean_text("".join(element.itertext()))


def parse_jats_xml(path: Path) -> tuple[TextUnit, ...]:
    root = ET.parse(path).getroot()
    units: list[TextUnit] = []
    abstract_index = 0
    for paragraph in root.findall(".//abstract//p"):
        text = _element_text(paragraph)
        if text:
            abstract_index += 1
            units.append(TextUnit("Abstract", f"Abstract ¶{abstract_index}", text))
    for section_index, section in enumerate(root.findall(".//body//sec"), start=1):
        title_element = section.find("./title")
        title = _element_text(title_element) if title_element is not None else f"Section {section_index}"
        paragraph_index = 0
        for paragraph in section.findall("./p"):
            text = _element_text(paragraph)
            if text:
                paragraph_index += 1
                units.append(TextUnit(title, f"{title} ¶{paragraph_index}", text))
    if not units:
        raise ValueError(f"no JATS paragraphs extracted from {path}")
    return tuple(units)


def parse_pdf(path: Path) -> tuple[TextUnit, ...]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF ingestion requires pypdf") from exc
    reader = PdfReader(path)
    units = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = _clean_text(page.extract_text() or "")
        if text:
            units.append(TextUnit("Manual", f"p. {page_number}", text))
    if not units:
        raise ValueError(f"no PDF text extracted from {path}")
    return tuple(units)


def download_core_corpus(
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    timeout_s: int = 60,
) -> tuple[Path, ...]:
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []
    for source in load_catalog():
        if source.ingest_policy != "full_text":
            continue
        suffix = ".xml" if source.source_format == "jats_xml" else ".pdf"
        target = raw_dir / f"{source.source_id}{suffix}"
        if target.exists() and _valid_download(target.read_bytes(), source.source_format):
            downloaded.append(target)
            continue
        last_error = None
        for attempt in range(3):
            try:
                response = requests.get(source.download_url, timeout=timeout_s)
                response.raise_for_status()
                if not _valid_download(response.content, source.source_format):
                    raise ValueError(
                        f"unexpected content for {source.source_format}: {source.download_url}"
                    )
                target.write_bytes(response.content)
                last_error = None
                break
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(attempt + 1)
        if last_error is not None:
            raise RuntimeError(f"failed to download {source.source_id}") from last_error
        downloaded.append(target)
    return tuple(downloaded)


def _valid_download(content: bytes, source_format: str) -> bool:
    if source_format == "pdf":
        return content.lstrip().startswith(b"%PDF")
    if source_format == "jats_xml":
        return b"<article" in content[:10000]
    return False


def build_chunk_snapshot(
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    target_tokens: int = 350,
    overlap_tokens: int = 60,
) -> tuple[KnowledgeChunk, ...]:
    raw_dir = data_dir / "raw"
    all_chunks: list[KnowledgeChunk] = []
    manifest_sources = []
    for source in load_catalog():
        if source.ingest_policy != "full_text":
            continue
        suffix = ".xml" if source.source_format == "jats_xml" else ".pdf"
        path = raw_dir / f"{source.source_id}{suffix}"
        if not path.exists():
            raise FileNotFoundError(f"source is not downloaded: {path}")
        raw_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        units = parse_jats_xml(path) if source.source_format == "jats_xml" else parse_pdf(path)
        normalized_digest = hashlib.sha256(
            "\n".join(
                f"{unit.section}\x1f{unit.locator}\x1f{unit.text}" for unit in units
            ).encode("utf-8")
        ).hexdigest()
        chunks = chunk_units(
            source,
            units,
            target_tokens=target_tokens,
            overlap_tokens=overlap_tokens,
            document_id=source.source_id,
            version_id=normalized_digest,
        )
        all_chunks.extend(chunks)
        manifest_sources.append(
            {
                "source_id": source.source_id,
                "raw_sha256": raw_digest,
                "version_id": normalized_digest,
                "unit_count": len(units),
                "chunk_count": len(chunks),
            }
        )
    data_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = data_dir / "chunks.jsonl"
    chunks_path.write_text(
        "\n".join(chunk.model_dump_json() for chunk in all_chunks) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "corpus_version": CORPUS_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "target_tokens": target_tokens,
        "overlap_tokens": overlap_tokens,
        "sources": manifest_sources,
        "chunk_count": len(all_chunks),
    }
    (data_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return tuple(all_chunks)


def load_chunk_snapshot(data_dir: Path = DEFAULT_DATA_DIR) -> tuple[KnowledgeChunk, ...]:
    path = data_dir / "chunks.jsonl"
    return tuple(
        KnowledgeChunk.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
