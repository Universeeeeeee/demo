"""
treadmill_processor.py — Placeholder for treadmill-mode processors

These will be implemented in a future task.
"""

from __future__ import annotations

from typing import List


class TreadmillProcessor:
    """Placeholder processor for Treadmill Gait and Treadmill Running modes."""

    _DISPLAY_MODES = {
        "treadmill_gait": "跑步机步态",
        "treadmill_running": "跑步机跑步",
    }

    def __init__(self, config, mode_name: str) -> None:
        self.name = mode_name
        self.display_mode = self._DISPLAY_MODES.get(mode_name, mode_name)

    def reset(self) -> None:
        raise NotImplementedError("TreadmillProcessor.reset not yet implemented")

    def process_raw_frame(
        self, contact_bits: List[int], rel_time: float, abs_time: float
    ) -> List[object]:
        raise NotImplementedError("TreadmillProcessor.process_raw_frame not yet implemented")

    def build_report(
        self, reason: str, export_frames: tuple, export_timestamps: tuple
    ):
        raise NotImplementedError("TreadmillProcessor.build_report not yet implemented")
