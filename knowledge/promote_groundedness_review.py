"""Promote a completed local review into the tracked frozen V1 artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from .ingestion import DEFAULT_DATA_DIR
from .release_artifacts import (
    DEFAULT_FROZEN_REVIEW_PATH,
    promote_groundedness_review,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_DATA_DIR / "groundedness_review.json",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_FROZEN_REVIEW_PATH,
    )
    args = parser.parse_args()
    promote_groundedness_review(args.source, args.destination)


if __name__ == "__main__":
    main()
