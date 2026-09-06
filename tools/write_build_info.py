"""Write build-time Git metadata for the frozen application."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path


def build_info() -> dict:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except Exception:
        commit = "unknown"
        dirty = "unknown"
    return {
        "git_commit": commit or "unknown",
        "git_dirty": dirty,
        "build_time": datetime.now().astimezone().isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_info(), indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
