"""Tests for mode dispatching and delegation in GaitEngine facade."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from config.test_config import default_jump_config
from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig
from engine.gait_engine import GaitEngine


def test_gait_engine_uses_jump_processor_for_jump_config():
    engine = GaitEngine(config=default_jump_config())

    assert engine.mode == "纵跳"
    assert engine.processor_name == "jump"


def test_gait_engine_uses_treadmill_processor_for_treadmill_running_config():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=10.0,
        direction="Interface side",
    )
    engine = GaitEngine(config=config)

    assert engine.mode == "跑步机跑步"
    assert engine.processor_name == "treadmill_running"


def test_gait_engine_build_report_delegates_to_processor():
    class FakeProcessor:
        name = "fake"
        display_mode = "Fake"

        def build_report(self, reason, export_frames, export_timestamps):
            return {
                "reason": reason,
                "export_frames": export_frames,
                "export_timestamps": export_timestamps,
            }

    engine = GaitEngine(config=default_jump_config())
    engine._processor = FakeProcessor()
    engine._export_frames.append([1, 0])
    engine._export_timestamps.append(0.25)

    report = engine.build_report("manual")

    assert report == {
        "reason": "manual",
        "export_frames": ([1, 0],),
        "export_timestamps": (0.25,),
    }
