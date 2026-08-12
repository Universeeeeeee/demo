"""Minimal adapter from the sequential loop to ReportRepository checkpoints."""

from __future__ import annotations

from reporting.models import SequentialLoopCheckpoint
from reporting.repository import ReportRepository


class RepositoryCheckpointSink:
    def __init__(self, repository: ReportRepository, run_id: str):
        self._repository = repository
        self._run_id = run_id

    def save(self, checkpoint: SequentialLoopCheckpoint) -> None:
        self._repository.save_analysis_checkpoint(self._run_id, checkpoint)


__all__ = ["RepositoryCheckpointSink"]
