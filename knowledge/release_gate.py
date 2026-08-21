"""Read the tracked V1 release decision without hidden environment overrides."""

from __future__ import annotations

import json
from pathlib import Path

from .catalog import DEFAULT_CATALOG_PATH
from .release_artifacts import (
    DEFAULT_MANIFEST_PATH,
    RELEASE_GATE_VERSION,
    ReleaseArtifactError,
    build_release_fingerprint,
)


DEFAULT_RELEASE_GATE_PATH = Path(__file__).with_name("v1_release_gate.json")

RELEASE_GATE_ENABLED = "enabled"
RELEASE_GATE_DISABLED = "disabled"
RELEASE_GATE_INVALID = "invalid"


def v1_release_status(
    path: Path = DEFAULT_RELEASE_GATE_PATH,
    *,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    review_path: Path | None = None,
) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return RELEASE_GATE_INVALID
    if not isinstance(payload, dict):
        return RELEASE_GATE_INVALID
    if payload.get("enabled") is False:
        return RELEASE_GATE_DISABLED
    if payload.get("enabled") is not True:
        return RELEASE_GATE_INVALID
    required = (
        "retrieval_baseline_passed",
        "metadata_gates_passed",
        "automated_generator_e2e_passed",
        "human_groundedness_review_passed",
    )
    if not all(payload.get(item) is True for item in required):
        return RELEASE_GATE_INVALID
    if payload.get("gate_version") != RELEASE_GATE_VERSION:
        return RELEASE_GATE_INVALID
    artifact_value = payload.get("review_artifact")
    expected_fingerprint = payload.get("release_fingerprint")
    if not isinstance(artifact_value, str) or not artifact_value:
        return RELEASE_GATE_INVALID
    if not isinstance(expected_fingerprint, str) or len(expected_fingerprint) != 64:
        return RELEASE_GATE_INVALID
    resolved_review_path = (
        Path(review_path)
        if review_path is not None
        else Path(path).parent / artifact_value
    )
    try:
        actual_fingerprint = build_release_fingerprint(
            catalog_path=catalog_path,
            manifest_path=manifest_path,
            review_path=resolved_review_path,
        )
    except (OSError, ValueError, TypeError, ReleaseArtifactError):
        return RELEASE_GATE_INVALID
    if actual_fingerprint != expected_fingerprint:
        return RELEASE_GATE_INVALID
    return RELEASE_GATE_ENABLED


def v1_release_enabled(
    path: Path = DEFAULT_RELEASE_GATE_PATH,
    *,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    review_path: Path | None = None,
) -> bool:
    return v1_release_status(
        path,
        catalog_path=catalog_path,
        manifest_path=manifest_path,
        review_path=review_path,
    ) == RELEASE_GATE_ENABLED
