from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.jump_timing_diagnostics import (  # noqa: E402
    FrameSample,
    TimingConfig,
    compute_jump_rows,
    iter_excel_led_frames,
    run_detector,
)


def _bits(start: int | None = None, end: int | None = None) -> list[int]:
    bits = [0] * 96
    if start is not None and end is not None:
        for index in range(start, end + 1):
            bits[index] = 1
    return bits


def _frame(index: int, timestamp: float, bits: list[int]) -> FrameSample:
    return FrameSample(index=index, timestamp=timestamp, bits=bits)


def test_current_mode_matches_confirm_frame_and_streak_decay() -> None:
    config = TimingConfig(confirm_samples=2)
    frames = [
        _frame(1, 0.00, _bits(20, 31)),
        _frame(2, 0.01, _bits()),
        _frame(3, 0.02, _bits(20, 31)),
        _frame(4, 0.03, _bits(20, 31)),
        _frame(5, 0.04, _bits()),
        _frame(6, 0.05, _bits()),
    ]

    result = run_detector(frames, "current", config)

    assert [(event.kind, event.time, event.confirm_time) for event in result.events] == [
        ("touch", 0.03, 0.03),
        ("lift", 0.05, 0.05),
    ]
    touch_trace = result.traces[1]
    assert touch_trace.touch_streak == 0


def test_compensated_mode_only_backfills_event_time() -> None:
    config = TimingConfig(confirm_samples=2)
    frames = [
        _frame(1, 0.00, _bits(20, 31)),
        _frame(2, 0.01, _bits(20, 31)),
        _frame(3, 0.02, _bits()),
        _frame(4, 0.03, _bits()),
    ]

    current = run_detector(frames, "current", config)
    compensated = run_detector(frames, "compensated", config)

    assert [(event.kind, event.confirm_time) for event in compensated.events] == [
        (event.kind, event.confirm_time) for event in current.events
    ]
    assert [(event.kind, event.time) for event in compensated.events] == [
        ("touch", 0.00),
        ("lift", 0.02),
    ]


def test_onset_mode_uses_raw_small_cluster_for_time_and_valid_cluster_for_confirm() -> None:
    config = TimingConfig(
        confirm_samples=2,
        touch_onset_min_leds=2,
        lift_onset_max_leds=3,
        confirm_window_s=0.25,
    )
    frames = [
        _frame(1, 0.00, _bits(20, 21)),  # raw onset, invalid for confirm
        _frame(2, 0.01, _bits(20, 22)),  # still invalid for confirm
        _frame(3, 0.02, _bits(20, 23)),  # valid confirm frame 1
        _frame(4, 0.03, _bits(20, 23)),  # valid confirm frame 2
        _frame(5, 0.04, _bits(20, 21)),  # lift onset, still invalid/low
        _frame(6, 0.05, _bits()),
    ]

    result = run_detector(frames, "onset", config)

    assert result.events[0].kind == "touch"
    assert result.events[0].time == 0.00
    assert result.events[0].confirm_time == 0.03
    assert result.events[0].onset_time == 0.00
    assert result.traces[0].raw_primary_cluster_length == 2
    assert result.traces[0].valid_primary_cluster_length == 0
    assert result.traces[2].valid_primary_cluster_length == 4


def test_associated_mode_backfills_touch_to_same_raw_track_first_seen() -> None:
    config = TimingConfig(confirm_samples=2)
    frames = [
        _frame(1, 0.00, _bits(20, 22)),  # first observable contact, not 1 LED
        _frame(2, 0.01, _bits()),  # short drop-out should not break the track
        _frame(3, 0.02, _bits(20, 22)),
        _frame(4, 0.03, _bits(20, 23)),  # confirm frame 1
        _frame(5, 0.04, _bits(20, 23)),  # confirm frame 2
    ]

    result = run_detector(frames, "associated", config)

    assert len(result.events) == 1
    touch = result.events[0]
    assert touch.kind == "touch"
    assert touch.time == 0.00
    assert touch.first_confirm_frame_time == 0.03
    assert touch.confirm_time == 0.04


def test_associated_mode_does_not_attach_far_isolated_small_noise_to_touch() -> None:
    config = TimingConfig(confirm_samples=2)
    frames = [
        _frame(1, 0.00, _bits(5, 5)),  # isolated 1 LED noise, far from touch
        _frame(2, 0.01, _bits()),
        _frame(3, 0.02, _bits(20, 22)),
        _frame(4, 0.03, _bits(20, 31)),  # confirm frame 1
        _frame(5, 0.04, _bits(20, 31)),  # confirm frame 2
    ]

    result = run_detector(frames, "associated", config)

    assert len(result.events) == 1
    assert result.events[0].kind == "touch"
    assert result.events[0].time == 0.02


def test_current_mode_does_not_oscillate_on_sustained_four_led_contact() -> None:
    frames = [
        _frame(index, index * 0.001, _bits(20, 23))
        for index in range(20)
    ]

    result = run_detector(frames, "current", TimingConfig(confirm_samples=2))

    assert [event.kind for event in result.events] == ["touch"]


def test_lift_associated_mode_backfills_last_seen_without_upgrading_confirmation() -> None:
    config = TimingConfig(confirm_samples=2)
    frames = [
        _frame(1, 0.00, _bits(20, 31)),
        _frame(2, 0.01, _bits(20, 31)),  # touch confirm
        _frame(3, 0.02, _bits()),  # lift condition frame 1
        _frame(4, 0.03, _bits(20, 22)),  # below 4 LEDs; lift confirms here
        _frame(5, 0.04, _bits(20, 22)),  # too late to be bridged into lift
        _frame(6, 0.05, _bits()),
    ]

    result = run_detector(frames, "lift_associated", config)

    assert [(event.kind, event.confirm_time) for event in result.events] == [
        ("touch", 0.01),
        ("lift", 0.03),
    ]
    lift = result.events[1]
    assert lift.time == 0.03
    assert lift.first_confirm_frame_time == 0.02


def test_excel_reader_preserves_all_zero_frames_and_timestamps(tmp_path: Path) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "LED Frames"
    sheet.append(["timestamp", "hex_string"])
    sheet.append([0.10, "00 00 00 00 00 00 00 00 00 00 00 00"])
    sheet.append([0.20, "ff 00 00 00 00 00 00 00 00 00 00 00"])
    path = tmp_path / "frames.xlsx"
    workbook.save(path)

    frames = list(iter_excel_led_frames(path))

    assert len(frames) == 2
    assert frames[0].timestamp == 0.10
    assert sum(frames[0].bits) == 0
    assert frames[1].timestamp == 0.20
    assert sum(frames[1].bits) == 8


def test_production_equivalent_pairing_skips_first_contact_time() -> None:
    events = run_detector(
        [
            _frame(1, 0.0, _bits(20, 31)),
            _frame(2, 0.1, _bits()),
            _frame(3, 0.4, _bits(20, 31)),
            _frame(4, 0.6, _bits()),
            _frame(5, 1.0, _bits(20, 31)),
        ],
        "current",
        TimingConfig(confirm_samples=1),
    ).events

    raw_rows = compute_jump_rows(events, "raw_triplet")
    production_rows = compute_jump_rows(events, "production_equivalent")

    assert [round(row.contact_time_s, 6) for row in raw_rows] == [0.1, 0.2]
    assert [round(row.air_time_s, 6) for row in raw_rows] == [0.3, 0.4]
    assert [
        round(row.contact_time_s, 6)
        for row in production_rows
        if row.contact_time_s is not None
    ] == [0.2]
    assert [
        round(row.air_time_s, 6)
        for row in production_rows
        if row.air_time_s is not None
    ] == [0.3, 0.4]
