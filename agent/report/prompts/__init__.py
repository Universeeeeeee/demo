"""Versioned Report Agent prompt resources."""

from pathlib import Path


PROMPT_VERSION = "report-agent-system/2.0"
SEQUENTIAL_PROMPT_VERSION = "report-agent-sequential-system/3.0"


def load_system_prompt() -> str:
    return (Path(__file__).resolve().parent / "system.md").read_text(
        encoding="utf-8"
    ).strip()


def load_sequential_system_prompt() -> str:
    return (Path(__file__).resolve().parent / "sequential_system.md").read_text(
        encoding="utf-8"
    ).strip()
