"""Protection tests for Phase 9.1 engine/report behavior."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.test_report import (
    G,
    GaitTestReport,
    JumpTestReport,
    _cadences,
    _jump_heights,
    _max_or_zero,
    _mean,
    _min_or_zero,
    _population_std,
    _positive_values,
    build_report,
)
from engine.contact_tracker import ContactBasedGaitTracker
from engine.single_foot_tracker import (
    LedFrame as SingleFootFrame,
    SingleFootDetector,
)
from engine.spatial_clusterer import (
    Cluster as SpatialCluster,
    ClusterTracker,
    TrackedCluster,
    compute_gait_parameters,
    extract_clusters,
)


def _bits(start: int | None = None, end: int | None = None, cols: int = 96) -> list[int]:
    bits = [0] * cols
    if start is not None and end is not None:
        for idx in range(start, end + 1):
            bits[idx] = 1
    return bits


def _spatial_cluster(centroid_cm: float, length: int = 12) -> SpatialCluster:
    return SpatialCluster(
        start=0,
        end=length - 1,
        length=length,
        centroid_idx=centroid_cm,
        centroid_cm=centroid_cm,
    )


def _tracked(
    track_id: int,
    appear: float,
    disappear: float,
    start_cm: float,
    end_cm: float,
    foot: str,
) -> TrackedCluster:
    return TrackedCluster(
        track_id=track_id,
        appear_time=appear,
        disappear_time=disappear,
        centroid_start=start_cm,
        centroid_end=end_cm,
        foot_label=foot,
        length_cm=12.0,
        seen_count=2,
        centroid_history=[(appear, start_cm), (disappear, end_cm)],
    )


def test_single_foot_detector_confirms_touch_and_lift_after_required_samples():
    detector = SingleFootDetector(confirm_samples=2)
    contact_bits = _bits(20, 31)

    events = []
    for frame in [
        SingleFootFrame(0.00, contact_bits),
        SingleFootFrame(0.01, contact_bits),
        SingleFootFrame(0.02, _bits()),
        SingleFootFrame(0.03, _bits()),
    ]:
        events.extend(detector.consume(frame))

    assert [event.kind for event in events] == ["touch", "lift"]
    assert events[0].time == 0.01
    assert math.isclose(events[0].ratio, 12 / 96)
    assert math.isclose(events[0].centroid_cm, 25.5 * 1.04)
    assert events[1].time == 0.03
    assert events[1].ratio == 0.0
    assert events[1].centroid_cm is None


def test_single_foot_detector_ignores_clusters_shorter_than_four_leds():
    detector = SingleFootDetector(confirm_samples=1)

    events = detector.consume(SingleFootFrame(0.0, _bits(20, 22)))

    assert events == []


def test_spatial_extract_clusters_filters_short_cluster_and_computes_centroid():
    bits = _bits(5, 13)
    bits[20:32] = [1] * 12

    clusters = extract_clusters(bits)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.start == 20
    assert cluster.end == 31
    assert cluster.length == 12
    assert cluster.centroid_idx == 25.5
    assert math.isclose(cluster.centroid_cm, 25.5 * 1.04)


def test_spatial_cluster_tracker_keeps_nearby_frames_in_one_valid_track():
    tracker = ClusterTracker(
        max_shift_led=5,
        t_min_s=0.05,
        spacing_cm=1.0,
        max_missed_frames=1,
    )

    tracker.update(0.00, [_spatial_cluster(10.0)])
    tracker.update(0.06, [_spatial_cluster(12.0)])
    tracker.update(0.10, [])
    tracker.update(0.11, [])
    tracks = tracker.finalize()

    assert len(tracks) == 1
    track = tracks[0]
    assert track.track_id == 0
    assert track.appear_time == 0.00
    assert track.disappear_time == 0.06
    assert track.centroid_start == 10.0
    assert track.centroid_end == 12.0
    assert track.seen_count == 2
    assert track.is_active is False


def test_spatial_gait_parameters_use_same_foot_stride_and_adjacent_step_time():
    tracks = [
        _tracked(0, 0.0, 0.2, 10.0, 12.0, "A"),
        _tracked(1, 0.5, 0.8, 20.0, 21.0, "B"),
        _tracked(2, 1.0, 1.3, 30.0, 32.0, "A"),
    ]

    cycles, summary = compute_gait_parameters(tracks, events=[])

    cycles_by_time = sorted(cycles, key=lambda cycle: cycle.strike_time)
    assert [cycle.foot_label for cycle in cycles_by_time] == ["A", "B", "A"]
    assert cycles_by_time[0].stride_time == 1.0
    assert cycles_by_time[0].stride_length_cm == 20.0
    assert cycles_by_time[0].velocity_cm_s == 20.0
    assert cycles_by_time[0].step_time == 0.5
    assert math.isclose(summary["avg_support_time_s"], (0.2 + 0.3 + 0.3) / 3)
    assert summary["avg_stride_time_s"] == 1.0
    assert summary["avg_stride_length_cm"] == 20.0
    assert summary["avg_velocity_cm_s"] == 20.0
    assert summary["avg_step_time_s"] == 0.5
    assert summary["avg_step_length_cm"] == 10.0


def test_contact_tracker_emits_touch_then_lift_for_confirmed_contact():
    tracker = ContactBasedGaitTracker(
        contact_confirm_frames=2,
        contact_lift_miss_frames=2,
        min_step_interval=0.0,
        arm_frames=2,
        max_contact_age=1.0,
        min_cluster_length=10.0,
        max_centroid_jitter=10.0,
        jitter_window=2,
    )
    active = [{"track_id": 1, "centroid_cm": 20.0, "length_cm": 15.0}]

    assert tracker.process_frame(0.0, []) == []
    assert tracker.process_frame(0.1, []) == []
    assert tracker.process_frame(0.2, active) == []
    touch_events = tracker.process_frame(0.3, active)

    assert [event.kind for event in touch_events] == ["touch"]
    touch = touch_events[0].contact
    assert touch.touch_time == 0.2
    assert touch.centroid_at_touch == 20.0
    assert tracker.touch_count == 1

    assert tracker.process_frame(0.4, []) == []
    lift_events = tracker.process_frame(0.5, [])

    assert [event.kind for event in lift_events] == ["lift"]
    lifted = lift_events[0].contact
    assert lifted.lift_time == 0.3
    assert math.isclose(lifted.contact_duration, 0.1)
    assert tracker.lift_count == 1
    assert tracker.active_contacts == {}


def test_gait_report_defaults_visual_timeline_to_empty_tuple():
    report = GaitTestReport(
        touch_count=0,
        lift_count=0,
        stride_lengths=(),
        velocities=(),
        avg_stride=0.0,
        max_stride=0.0,
        avg_velocity=0.0,
        max_velocity=0.0,
    )

    assert report.visual_timeline == ()


def _compute_jump_report(
    reason, touch_count, lift_count, air_times, contact_times, cycle_times,
    export_frames, export_timestamps,
):
    """Replicate the former test_report.build_report jump path."""
    air = _positive_values(air_times)
    contact = _positive_values(contact_times)
    cycle = _positive_values(cycle_times)

    # Convert to immutable tuples
    export_frames = tuple(list(f) for f in export_frames)
    export_timestamps = tuple(export_timestamps)

    heights = _jump_heights(air)
    cadence_values = _cadences(cycle)
    avg_air = _mean(air)
    avg_contact = _mean(contact)
    avg_cycle = _mean(cycle)

    return JumpTestReport(
        touch_count=touch_count,
        lift_count=lift_count,
        air_times=air,
        contact_times=contact,
        cycle_times=cycle,
        avg_jump_height=_mean(heights),
        max_jump_height=_max_or_zero(heights),
        avg_air_time=avg_air,
        max_air_time=_max_or_zero(air),
        avg_contact_time=avg_contact,
        avg_cadence=60.0 / avg_cycle if avg_cycle > 0 else None,
        finish_reason=reason,
        jump_heights=heights,
        cadences=cadence_values,
        min_jump_height=_min_or_zero(heights),
        std_jump_height=_population_std(heights),
        min_air_time=_min_or_zero(air),
        std_air_time=_population_std(air),
        min_contact_time=_min_or_zero(contact),
        max_contact_time=_max_or_zero(contact),
        std_contact_time=_population_std(contact),
        export_frames=export_frames,
        export_timestamps=export_timestamps,
    )


def _make_mock_jump_engine(**overrides):
    """Create a mock engine with build_report for jump tests."""
    defaults = dict(
        touch_count=0, lift_count=0,
        air_times=(), contact_times=(), cycle_times=(),
        export_frames=(), export_timestamps=(),
    )
    attrs = {**defaults, **overrides}
    return type(
        "MockJumpEngine",
        (),
        {
            **attrs,
            "build_report": lambda self, reason="manual": _compute_jump_report(
                reason=reason,
                touch_count=self.touch_count,
                lift_count=self.lift_count,
                air_times=self.air_times,
                contact_times=self.contact_times,
                cycle_times=self.cycle_times,
                export_frames=self.export_frames,
                export_timestamps=self.export_timestamps,
            ),
        },
    )()


def test_build_report_creates_jump_snapshot_with_derived_metrics():
    engine = _make_mock_jump_engine(
        touch_count=4, lift_count=3,
        air_times=[0.4, 0.6],
        contact_times=[0.2, 0.3],
        cycle_times=[0.8, 1.2],
        export_frames=([1, 0], [0, 1]),
        export_timestamps=[1.0, 1.1],
    )

    report = build_report(engine, reason="manual")

    assert isinstance(report, JumpTestReport)
    assert report.touch_count == 4
    assert report.lift_count == 3
    assert report.air_times == (0.4, 0.6)
    assert report.contact_times == (0.2, 0.3)
    assert report.cycle_times == (0.8, 1.2)
    assert report.avg_air_time == 0.5
    assert report.max_air_time == 0.6
    assert report.avg_contact_time == 0.25
    expected_heights = (
        0.5 * G * (0.4 / 2) ** 2,
        0.5 * G * (0.6 / 2) ** 2,
    )
    assert report.jump_heights == expected_heights
    assert math.isclose(report.avg_jump_height, sum(expected_heights) / 2)
    assert math.isclose(report.max_jump_height, 0.5 * G * (0.6 / 2) ** 2)
    assert math.isclose(report.min_jump_height, 0.5 * G * (0.4 / 2) ** 2)
    assert math.isclose(report.std_air_time, 0.1)
    assert math.isclose(report.std_contact_time, 0.05)
    assert report.cadences == (75.0, 50.0)
    assert report.avg_cadence == 60.0
    assert report.finish_reason == "manual"
    assert report.export_frames == ([1, 0], [0, 1])
    assert report.export_timestamps == (1.0, 1.1)


def test_build_report_creates_gait_snapshot_and_averages_extra_metrics():
    engine = type(
        "MockGaitEngine",
        (),
        {
            "build_report": lambda self, reason="time_up": GaitTestReport(
                touch_count=3, lift_count=2,
                stride_lengths=(10.0, 20.0),
                velocities=(50.0, 70.0),
                avg_stride=15.0, max_stride=20.0,
                avg_velocity=60.0, max_velocity=70.0,
                foot_a_support_times=(0.3,),
                foot_b_support_times=(0.4, 0.5),
                imbalance_index=12.0,
                avg_double_support=0.12,
                avg_single_support=0.4,
                avg_acceleration=1.5,
                finish_reason="time_up",
                export_frames=([1, 1],),
                export_timestamps=(2.0,),
            ),
        },
    )()

    report = build_report(engine, reason="time_up")

    assert isinstance(report, GaitTestReport)
    assert report.touch_count == 3
    assert report.lift_count == 2
    assert report.stride_lengths == (10.0, 20.0)
    assert report.velocities == (50.0, 70.0)
    assert report.avg_stride == 15.0
    assert report.max_stride == 20.0
    assert report.avg_velocity == 60.0
    assert report.max_velocity == 70.0
    assert report.foot_a_support_times == (0.3,)
    assert report.foot_b_support_times == (0.4, 0.5)
    assert report.imbalance_index == 12.0
    assert report.avg_double_support == 0.12
    assert report.avg_single_support == 0.4
    assert report.avg_acceleration == 1.5
    assert report.finish_reason == "time_up"
    assert report.export_frames == ([1, 1],)
    assert report.export_timestamps == (2.0,)
