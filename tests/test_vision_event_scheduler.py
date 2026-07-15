import unittest

from vision.event_scheduler import EventWindowScheduler
from vision.foot_reference import (
    FootLabel,
    FootPoseSample,
    FrameSample,
    Landmark,
    VisionConfig,
    VisionDecision,
)


def _pose(timestamp_s: float) -> FootPoseSample:
    left = Landmark(0.4, 0.9, 0.0, 0.99, 0.99)
    right = Landmark(0.6, 0.7, 0.0, 0.99, 0.99)
    return FootPoseSample(
        timestamp_s,
        left,
        left,
        left,
        left,
        left,
        right,
        right,
        right,
        right,
        right,
    )


def _frames(start_ms: int, end_ms: int, step_ms: int) -> list[FrameSample]:
    return [
        FrameSample(captured_at_s=value / 1000.0, frame={"timestamp_ms": value})
        for value in range(start_ms, end_ms + 1, step_ms)
    ]


class _Infer:
    def __init__(self):
        self.timestamps: list[int] = []

    def __call__(self, frame, timestamp_ms: int):
        self.timestamps.append(timestamp_ms)
        return _pose(timestamp_ms / 1000.0)


def _classify(event_id, event_time_s, samples, _config):
    return VisionDecision(
        event_id,
        FootLabel.LEFT,
        0.99,
        f"sample_count={len(samples)}",
        event_time_s,
    )


class EventWindowSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.config = VisionConfig(
            pre_event_ms=100,
            post_event_ms=60,
            inference_interval_ms=20,
            decision_timeout_ms=200,
            frame_buffer_ms=500,
        )

    def test_waits_until_window_right_edge_is_available(self):
        scheduler = EventWindowScheduler(self.config)
        scheduler.add_frames(_frames(0, 190, 10))
        scheduler.add_event(1, 0.150, submitted_at_s=0.150)

        self.assertEqual(scheduler.process_ready(_Infer(), _classify, now_s=0.190), [])

        scheduler.add_frame({"timestamp_ms": 210}, 0.210)
        decisions = scheduler.process_ready(_Infer(), _classify, now_s=0.210)
        self.assertEqual([item.event_id for item in decisions], [1])

    def test_overlapping_windows_reuse_strictly_increasing_timestamps(self):
        scheduler = EventWindowScheduler(self.config)
        scheduler.add_frames(_frames(0, 300, 10))
        scheduler.add_event(1, 0.150, submitted_at_s=0.150)
        scheduler.add_event(2, 0.180, submitted_at_s=0.180)
        infer = _Infer()

        decisions = scheduler.process_ready(infer, _classify, now_s=0.300)

        self.assertEqual([item.event_id for item in decisions], [1, 2])
        self.assertEqual(infer.timestamps, sorted(set(infer.timestamps)))
        self.assertGreater(len(infer.timestamps), 0)

    def test_equal_integer_milliseconds_are_inferred_once(self):
        scheduler = EventWindowScheduler(self.config)
        scheduler.add_frame("window-start", 0.050)
        scheduler.add_frame("first", 0.1001)
        scheduler.add_frame("same-ms", 0.1009)
        scheduler.add_frame("window-end", 0.210)
        scheduler.add_event(8, 0.150, submitted_at_s=0.150)
        infer = _Infer()

        scheduler.process_ready(infer, _classify, now_s=0.210)

        self.assertEqual(infer.timestamps.count(100), 1)

    def test_events_are_decided_in_event_time_order(self):
        scheduler = EventWindowScheduler(self.config)
        scheduler.add_frames(_frames(0, 300, 10))
        scheduler.add_event(2, 0.180, submitted_at_s=0.180)
        scheduler.add_event(1, 0.150, submitted_at_s=0.190)

        decisions = scheduler.process_ready(_Infer(), _classify, now_s=0.300)

        self.assertEqual([item.event_id for item in decisions], [1, 2])

    def test_expired_old_window_returns_unknown_without_rewinding(self):
        scheduler = EventWindowScheduler(self.config)
        scheduler.add_frames(_frames(500, 900, 20))
        scheduler.add_event(3, 0.400, submitted_at_s=0.900)

        decisions = scheduler.process_ready(_Infer(), _classify, now_s=0.900)

        self.assertEqual(decisions[0].label, FootLabel.UNKNOWN)
        self.assertEqual(decisions[0].reason, "frame_window_expired")

    def test_timeout_without_future_frames_returns_unknown(self):
        scheduler = EventWindowScheduler(self.config)
        scheduler.add_frames(_frames(0, 150, 10))
        scheduler.add_event(4, 0.150, submitted_at_s=0.150)

        decisions = scheduler.process_ready(_Infer(), _classify, now_s=0.351)

        self.assertEqual(decisions[0].label, FootLabel.UNKNOWN)
        self.assertEqual(decisions[0].reason, "decision_timeout")

    def test_reset_clears_cursor_events_frames_and_pose_cache(self):
        scheduler = EventWindowScheduler(self.config)
        scheduler.add_frames(_frames(0, 300, 20))
        scheduler.add_event(1, 0.150, submitted_at_s=0.150)
        scheduler.process_ready(_Infer(), _classify, now_s=0.300)

        scheduler.reset()

        self.assertEqual(scheduler.pending_event_count, 0)
        self.assertEqual(scheduler.frame_count, 0)
        self.assertEqual(scheduler.pose_cache_count, 0)
        self.assertIsNone(scheduler.inference_cursor_ms)


if __name__ == "__main__":
    unittest.main()
