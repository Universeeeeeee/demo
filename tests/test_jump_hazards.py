from __future__ import annotations

import pytest

from config.test_config import default_jump_config
from engine.gait_engine import GaitEngine
from engine.modes.jump_processor import JumpProcessor
from engine.single_foot_tracker import LedFrame, SingleFootDetector


def _bits(length: int, start: int = 20) -> list[int]:
    bits = [0] * 96
    start = min(start, 96 - length)
    for index in range(start, start + length):
        bits[index] = 1
    return bits


def _consume(detector: SingleFootDetector, samples: list[tuple[float, int]]):
    events = []
    for timestamp, length in samples:
        events.extend(detector.consume(LedFrame(timestamp, _bits(length))))
    return events


@pytest.mark.parametrize("length", [4, 12, 37, 50])
def test_touch_range_is_inclusive_from_4_to_50_columns(length):
    detector = SingleFootDetector(confirm_samples=2)

    events = _consume(detector, [(0.0, length), (0.001, length)])

    assert [event.kind for event in events] == ["touch"]
    assert detector.state == "ground"


@pytest.mark.parametrize("length", [3, 51, 96])
def test_out_of_range_clusters_do_not_create_touch(length):
    detector = SingleFootDetector(confirm_samples=2)

    events = _consume(detector, [(0.0, length), (0.001, length)])

    assert events == []
    assert detector.state == "air"


@pytest.mark.parametrize("length", [51, 96])
def test_oversized_cluster_emits_one_non_counting_quality_notice(length):
    detector = SingleFootDetector(confirm_samples=2)

    _consume(detector, [(0.0, length), (0.001, length), (0.002, length)])

    notices = detector.pop_quality_notices()
    assert len(notices) == 1
    assert notices[0].kind == "contact_cluster_above_limit"
    assert notices[0].cluster_length == length


def _feed_processor(
    processor: JumpProcessor, samples: list[tuple[float, int]]
):
    events = []
    for timestamp, length in samples:
        events.extend(processor.process_raw_frame(_bits(length), timestamp, timestamp))
    return events


def _one_jump_samples(
    lift_time: float = 0.100, touch_time: float = 0.500
) -> list[tuple[float, int]]:
    return [
        (0.000, 12),
        (0.001, 12),
        (lift_time, 0),
        (lift_time + 0.001, 0),
        (touch_time, 12),
        (touch_time + 0.001, 12),
    ]


def test_completed_jumps_is_derived_from_included_air_times():
    processor = JumpProcessor(default_jump_config())

    _feed_processor(processor, _one_jump_samples())

    assert processor.completed_jumps == 1
    assert processor.completed_jumps == len(processor.air_times)
    assert processor.touch_count == 2
    assert processor.lift_count == 1


def test_jump_records_align_contact_and_cycle_with_the_second_landing():
    processor = JumpProcessor(default_jump_config())
    samples = _one_jump_samples() + [
        (0.600, 0),
        (0.601, 0),
        (1.000, 12),
        (1.001, 12),
    ]

    _feed_processor(processor, samples)
    report = processor.build_report("manual", (), ())

    assert len(report.jump_results) == 2
    assert report.jump_results[0].contact_time_s is None
    assert report.jump_results[0].cycle_time_s is None
    assert report.jump_results[1].contact_time_s == pytest.approx(0.100)
    assert report.jump_results[1].cycle_time_s == pytest.approx(0.500)
    assert report.cycle_times == pytest.approx((0.500,))


def test_filtered_flight_does_not_advance_completed_jumps():
    config = default_jump_config()
    config.max_flight_time = 200
    processor = JumpProcessor(config)

    _feed_processor(processor, _one_jump_samples())

    assert processor.completed_jumps == 0
    assert processor.cycle_times == []
    report = processor.build_report("manual", (), ())
    assert len(report.jump_results) == 1
    assert not report.jump_results[0].is_included_in_statistics
    assert (
        report.jump_results[0].statistics_exclusion_reason
        == "flight_above_configured_max"
    )


def test_engine_stops_only_after_target_landing_is_settled():
    config = default_jump_config()
    config.number_of_jumps = 1
    engine = GaitEngine(config=config)
    engine.set_start_time(100.0)
    reasons = []
    order = []
    engine.hop_event.connect(
        lambda event: order.append("hop")
        if getattr(event, "_air_time", None) is not None
        else None
    )
    engine.test_finished.connect(reasons.append)
    engine.test_finished.connect(lambda _reason: order.append("finished"))

    for offset, length in _one_jump_samples()[:4]:
        engine.process_raw_frame(_bits(length), 100.0 + offset)
    assert reasons == []

    for offset, length in _one_jump_samples()[4:]:
        engine.process_raw_frame(_bits(length), 100.0 + offset)

    assert reasons == ["jump_count_reached"]
    assert engine._processor.completed_jumps == 1
    assert order == ["hop", "finished"]


def test_engine_does_not_stop_for_filtered_landing():
    config = default_jump_config()
    config.number_of_jumps = 1
    config.max_flight_time = 200
    engine = GaitEngine(config=config)
    engine.set_start_time(100.0)
    reasons = []
    engine.test_finished.connect(reasons.append)

    for offset, length in _one_jump_samples():
        engine.process_raw_frame(_bits(length), 100.0 + offset)

    assert reasons == []
    assert engine._processor.completed_jumps == 0


def test_engine_forwards_oversized_cluster_notice_without_hop_event():
    engine = GaitEngine(config=default_jump_config())
    engine.set_start_time(100.0)
    notices = []
    hops = []
    engine.jump_quality_notice.connect(notices.append)
    engine.hop_event.connect(hops.append)

    engine.process_raw_frame(_bits(51), 100.000)
    engine.process_raw_frame(_bits(51), 100.001)

    assert hops == []
    assert notices == [
        {
            "kind": "contact_cluster_above_limit",
            "time_s": pytest.approx(0.001),
            "cluster_length": 51,
            "ratio": pytest.approx(51 / 96),
        }
    ]


def test_controller_auto_stop_is_immediate_and_keeps_reason(monkeypatch):
    from ui.session_controller import SessionController

    controller = SessionController()
    calls = []
    monkeypatch.setattr(controller, "stop", lambda reason=None: calls.append(reason))

    controller._on_engine_finished("jump_count_reached")

    assert calls == ["jump_count_reached"]
    assert controller._finish_reason == "jump_count_reached"


def test_four_column_toe_landings_use_the_single_normal_touch_channel():
    processor = JumpProcessor(default_jump_config())
    samples = [
        (0.000, 4),
        (0.001, 4),
        (0.100, 0),
        (0.101, 0),
        (0.500, 4),
        (0.501, 4),
        (0.600, 0),
        (0.601, 0),
        (1.000, 4),
        (1.001, 4),
    ]

    _feed_processor(processor, samples)
    report = processor.build_report("manual", (), ())

    assert processor.touch_count == 3
    assert processor.lift_count == 2
    assert processor.completed_jumps == 2
    assert processor.air_times == pytest.approx([0.400, 0.400])
    assert all(result.is_included_in_statistics for result in report.jump_results)


def test_sustained_four_column_contact_does_not_oscillate():
    processor = JumpProcessor(default_jump_config())

    events = _feed_processor(
        processor,
        [(index * 0.001, 4) for index in range(100)],
    )

    assert [event.kind for event in events] == ["touch"]
    assert processor.touch_count == 1
    assert processor.lift_count == 0
    assert processor.completed_jumps == 0


def test_three_columns_confirm_lift_after_four_column_contact():
    detector = SingleFootDetector(confirm_samples=2)

    events = _consume(
        detector,
        [(0.000, 4), (0.001, 4), (0.002, 3), (0.003, 3)],
    )

    assert [event.kind for event in events] == ["touch", "lift"]


def test_soft_flight_threshold_and_frame_gap_only_add_quality_flags():
    config = default_jump_config()
    config.flight_time_review_threshold = 300
    processor = JumpProcessor(config)

    _feed_processor(processor, _one_jump_samples())
    report = processor.build_report("manual", (), ())

    assert processor.completed_jumps == 1
    flags = report.jump_results[0].quality_flags
    assert "flight_time_above_review_threshold" in flags
    assert "frame_gap_during_flight" in flags


def test_pause_resync_establishes_baseline_without_ghost_jump():
    processor = JumpProcessor(default_jump_config())
    _feed_processor(processor, [(0.000, 12), (0.001, 12)])

    processor.pause_boundary()
    events = _feed_processor(
        processor,
        [(0.100, 0), (0.101, 0), (0.200, 12), (0.201, 12)],
    )

    assert [event.kind for event in events] == ["touch"]
    assert processor.completed_jumps == 0
    assert processor.lift_count == 0
    assert processor.touch_count == 2


def test_resynced_ground_baseline_allows_next_complete_jump():
    processor = JumpProcessor(default_jump_config())
    processor.pause_boundary()

    events = _feed_processor(
        processor,
        [
            (0.000, 12), (0.001, 12),
            (0.100, 0), (0.101, 0),
            (0.500, 12), (0.501, 12),
        ],
    )

    assert [event.kind for event in events] == ["lift", "touch"]
    assert processor.completed_jumps == 1
    assert processor.air_times == pytest.approx([0.400])
    assert processor.touch_count == 1
    assert processor.lift_count == 1


def test_short_contact_characterization_remains_unchanged():
    config = default_jump_config()
    processor = JumpProcessor(config)
    samples = [
        (0.000, 12), (0.001, 12),
        (0.100, 0), (0.101, 0),
        (0.540, 12), (0.541, 12),
        (0.580, 0), (0.581, 0),
        (0.980, 12), (0.981, 12),
    ]

    _feed_processor(processor, samples)

    assert processor.air_times == pytest.approx([0.480, 0.400])
