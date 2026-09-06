from engine.contact_tracker import ContactBasedGaitTracker, ContactState
from engine.footprint_visualization import (
    FootprintTimelineRecorder,
    FootprintVisualFrame,
    build_visual_frame,
    led_index_to_unit_y,
)


def test_led_index_to_unit_y_bounds_and_midpoint():
    assert led_index_to_unit_y(0) == 0.0
    assert led_index_to_unit_y(95) == 1.0
    assert led_index_to_unit_y(47.5) == 0.5


def test_visual_frame_schema_has_no_presentation_opacity():
    frame = FootprintVisualFrame(timestamp_s=0.25, contact_bits=(0,) * 96)

    assert hasattr(frame, "contact_bits")
    assert hasattr(frame, "feet")
    assert not hasattr(frame, "opacity")


def test_build_visual_frame_derives_feet_from_contact_tracker():
    tracker = ContactBasedGaitTracker(
        contact_confirm_frames=1,
        contact_lift_miss_frames=2,
        min_step_interval=0.0,
        arm_frames=1,
        max_contact_age=1.0,
        min_cluster_length=10.0,
        max_centroid_jitter=10.0,
        jitter_window=1,
    )
    tracker.process_frame(0.0, [])
    tracker.process_frame(
        0.1,
        [{"track_id": 7, "centroid_cm": 21.0, "length_cm": 14.0}],
    )

    frame = build_visual_frame(0.1, [0] * 20 + [1] * 8 + [0] * 68, tracker)

    assert frame.timestamp_s == 0.1
    assert frame.contact_bits == tuple([0] * 20 + [1] * 8 + [0] * 68)
    assert len(frame.feet) == 1
    foot = frame.feet[0]
    assert foot.contact_id == 1
    assert foot.side == "left"
    assert foot.status == "confirmed"
    assert foot.centroid_cm == 21.0
    assert foot.length_cm == 14.0


def test_contact_tracker_alternates_foot_labels_without_double_support():
    tracker = ContactBasedGaitTracker(
        contact_confirm_frames=1,
        contact_lift_miss_frames=1,
        min_step_interval=0.0,
        arm_frames=1,
        max_contact_age=1.0,
        min_cluster_length=10.0,
        max_centroid_jitter=10.0,
        jitter_window=1,
    )

    tracker.process_frame(0.0, [])
    first_events = tracker.process_frame(
        0.1,
        [{"track_id": 1, "centroid_cm": 20.0, "length_cm": 24.0}],
    )
    tracker.process_frame(0.2, [])
    second_events = tracker.process_frame(
        0.8,
        [{"track_id": 2, "centroid_cm": 45.0, "length_cm": 24.0}],
    )

    assert first_events[0].contact.foot_label == "A"
    assert second_events[0].contact.foot_label == "B"
    assert build_visual_frame(0.8, [0] * 96, tracker).feet[0].side == "right"


def test_build_visual_frame_preserves_unknown_foot_measurements():
    tracker = ContactBasedGaitTracker(arm_frames=1)
    tracker.active_contacts[3] = ContactState(
        contact_id=3,
        status="candidate",
    )

    frame = build_visual_frame(0.2, [0] * 96, tracker)

    assert len(frame.feet) == 1
    foot = frame.feet[0]
    assert foot.centroid_cm is None
    assert foot.length_cm is None


def test_build_visual_frame_hides_ignored_startup_contact():
    tracker = ContactBasedGaitTracker(
        contact_confirm_frames=1,
        min_step_interval=0.0,
        max_contact_age=1.0,
        min_cluster_length=10.0,
        max_centroid_jitter=10.0,
        jitter_window=1,
        ignore_initial_contacts=True,
    )
    tracker.process_frame(
        0.0,
        [{"track_id": 1, "centroid_cm": 21.0, "length_cm": 14.0}],
    )

    frame = build_visual_frame(0.0, [0] * 96, tracker)

    assert frame.feet == ()


def test_timeline_recorder_uses_fixed_cadence_without_event_boundary_inserts():
    tracker = ContactBasedGaitTracker(arm_frames=1)
    recorder = FootprintTimelineRecorder(interval_s=0.10)

    assert recorder.record_if_due(0.00, [0] * 96, tracker) is not None
    assert recorder.record_if_due(0.03, [1] * 96, tracker) is None
    assert recorder.record_if_due(0.09, [1] * 96, tracker) is None
    assert recorder.record_if_due(0.10, [1] * 96, tracker) is not None

    assert [frame.timestamp_s for frame in recorder.frames] == [0.0, 0.1]
    assert isinstance(recorder.frames, tuple)

    pending = recorder.pop_pending()
    assert isinstance(pending, tuple)
    assert [frame.timestamp_s for frame in pending] == [0.0, 0.1]
    assert recorder.pop_pending() == ()
