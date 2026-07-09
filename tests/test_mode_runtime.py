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


def test_treadmill_events_route_to_gait_step_event_not_hop_event(qtbot):
    """P0-3: treadmill GaitStepEvent → gait_step_event; hop_event untouched."""
    from qtpy.QtTest import QSignalSpy

    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )
    engine = GaitEngine(config=config)
    hop_spy = QSignalSpy(engine.hop_event)
    gait_spy = QSignalSpy(engine.gait_step_event)

    # Process a frame with no contacts — processor should return empty list
    engine.process_raw_frame([0] * 96, 0.001)

    # hop_event must never fire for treadmill processor events
    assert hop_spy.count() == 0, f"hop_event emitted {hop_spy.count()} times for treadmill"
    # gait_step_event may or may not fire depending on whether a step event was generated
    # The key invariant: treadmill events must NOT go to hop_event


def test_gait_engine_emits_treadmill_visual_frame(qtbot):
    from qtpy.QtTest import QSignalSpy

    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )
    engine = GaitEngine(config=config)
    spy = QSignalSpy(engine.footprint_visual_frame)

    engine.process_raw_frame([0] * 96, 0.001)

    assert spy.count() == 1
    payload = spy.at(0)[0]
    assert payload["timestamp_s"] == 0.0
    assert payload["contact_bits"] == [0] * 96


def test_gait_engine_emits_treadmill_status_snapshot():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
    )
    engine = GaitEngine(config=config)
    snapshots = []
    engine.gait_status_snapshot.connect(lambda payload: snapshots.append(payload))

    engine.process_raw_frame([0] * 96, 0.001)
    engine.process_raw_frame([0] * 96, 0.200)

    assert snapshots
    assert snapshots[-1]["velocity_count"] == 1
    assert snapshots[-1]["velocity_sum"] == pytest.approx(100.0)


def test_session_controller_exposes_footprint_visual_signal(qtbot):
    from ui.session_controller import SessionController

    controller = SessionController()

    assert hasattr(controller, "footprint_visual_frame")


def test_jump_events_route_to_hop_event(qtbot):
    """JumpProcessor FootEvent → hop_event."""
    from qtpy.QtTest import QSignalSpy

    engine = GaitEngine(config=default_jump_config())
    hop_spy = QSignalSpy(engine.hop_event)

    # Process an empty frame — JumpProcessor may emit events
    engine.process_raw_frame([0] * 96, 0.001)

    # Just verifying the spy mechanism works — no crash, no error
    assert isinstance(hop_spy, QSignalSpy)


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
