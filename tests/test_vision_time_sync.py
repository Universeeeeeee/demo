import math
import unittest

from vision.time_sync import CameraClockSynchronizer, ClockSyncStatus


class CameraClockSynchronizerTests(unittest.TestCase):
    def _synchronizer(self, **overrides):
        options = {
            "min_samples": 3,
            "min_span_s": 0.2,
            "max_uncertainty_ms": 40.0,
            "drift_window_s": 10.0,
            "max_drift_ms": 40.0,
        }
        options.update(overrides)
        return CameraClockSynchronizer(**options)

    def test_freezes_fifth_percentile_offset_after_warmup(self):
        sync = self._synchronizer()

        first = sync.observe(0.0, 100.010)
        second = sync.observe(0.1, 100.112)
        ready = sync.observe(0.2, 100.211)

        self.assertIs(first.status, ClockSyncStatus.WARMING_UP)
        self.assertIs(second.status, ClockSyncStatus.WARMING_UP)
        self.assertIs(ready.status, ClockSyncStatus.READY)
        self.assertAlmostEqual(ready.offset_ms, 100010.1, places=3)
        self.assertAlmostEqual(ready.aligned_time_s, 100.2101, places=6)

        later = sync.observe(0.3, 100.313)
        self.assertAlmostEqual(later.offset_ms, ready.offset_ms, places=9)
        self.assertGreater(later.aligned_time_s, ready.aligned_time_s)

    def test_invalid_or_non_monotonic_sample_time_degrades_session(self):
        sync = self._synchronizer()
        sync.observe(0.0, 100.010)

        invalid = sync.observe(math.nan, 100.020)
        self.assertIs(invalid.status, ClockSyncStatus.DEGRADED)
        self.assertEqual(invalid.reason, "invalid_timestamp")
        self.assertIsNone(invalid.aligned_time_s)

        still_degraded = sync.observe(0.1, 100.110)
        self.assertIs(still_degraded.status, ClockSyncStatus.DEGRADED)

        sync.reset()
        sync.observe(0.2, 100.210)
        backwards = sync.observe(0.2, 100.220)
        self.assertIs(backwards.status, ClockSyncStatus.DEGRADED)
        self.assertEqual(backwards.reason, "non_monotonic_sample_time")

    def test_large_delivery_jitter_degrades_at_warmup_boundary(self):
        sync = self._synchronizer(max_uncertainty_ms=20.0)
        sync.observe(0.0, 100.000)
        sync.observe(0.1, 100.140)
        result = sync.observe(0.2, 100.200)

        self.assertIs(result.status, ClockSyncStatus.DEGRADED)
        self.assertEqual(result.reason, "clock_uncertainty_exceeded")
        self.assertGreater(result.uncertainty_ms, 20.0)

    def test_recent_offset_drift_degrades_ready_session(self):
        sync = self._synchronizer(
            min_samples=2,
            min_span_s=0.1,
            drift_window_s=1.0,
            max_drift_ms=20.0,
            max_uncertainty_ms=100.0,
        )
        sync.observe(0.0, 100.010)
        ready = sync.observe(0.1, 100.110)
        self.assertIs(ready.status, ClockSyncStatus.READY)

        result = ready
        for sample_time in (0.4, 0.7, 1.0, 1.1):
            result = sync.observe(sample_time, sample_time + 100.050)

        self.assertIs(result.status, ClockSyncStatus.DEGRADED)
        self.assertEqual(result.reason, "clock_drift_exceeded")

    def test_reset_starts_new_warmup_session(self):
        sync = self._synchronizer()
        sync.observe(0.0, 100.010)
        sync.observe(0.1, 100.110)
        sync.observe(0.2, 100.210)

        sync.reset()

        self.assertIs(sync.snapshot.status, ClockSyncStatus.WARMING_UP)
        self.assertIsNone(sync.snapshot.aligned_time_s)
        self.assertEqual(sync.sample_count, 0)

    def test_default_sync_becomes_ready_within_two_seconds_at_30_fps(self):
        sync = CameraClockSynchronizer()
        result = sync.snapshot

        for index in range(30):
            sample_time_s = index / 30.0
            result = sync.observe(sample_time_s, 100.0 + sample_time_s + 0.010)

        self.assertIs(result.status, ClockSyncStatus.READY)
        self.assertLess(29 / 30.0, 2.0)
        self.assertLess(result.warmup_ms, 2000.0)

    def test_frame_index_restart_degrades_until_explicit_reset(self):
        sync = self._synchronizer()
        sync.observe(0.0, 100.010, frame_index=1)
        sync.observe(0.1, 100.110, frame_index=2)

        restarted = sync.observe(0.2, 100.210, frame_index=1)

        self.assertIs(restarted.status, ClockSyncStatus.DEGRADED)
        self.assertEqual(restarted.reason, "non_monotonic_frame_index")

        sync.reset()
        accepted = sync.observe(0.0, 200.010, frame_index=1)
        self.assertIs(accepted.status, ClockSyncStatus.WARMING_UP)

    def test_degradation_preserves_latest_uncertainty_and_sample_period(self):
        sync = self._synchronizer()
        sync.observe(0.0, 100.010, frame_index=1)
        sync.observe(0.1, 100.112, frame_index=2)
        ready = sync.observe(0.2, 100.211, frame_index=3)

        degraded = sync.observe(math.nan, 100.300, frame_index=4)

        self.assertIs(degraded.status, ClockSyncStatus.DEGRADED)
        self.assertEqual(degraded.uncertainty_ms, ready.uncertainty_ms)
        self.assertEqual(degraded.sample_period_ms, ready.sample_period_ms)
        self.assertEqual(degraded.warmup_ms, ready.warmup_ms)

    def test_ready_history_is_bounded_to_the_drift_window(self):
        sync = self._synchronizer(
            min_samples=2,
            min_span_s=0.1,
            drift_window_s=1.0,
        )

        for index in range(51):
            sample_time_s = index / 10.0
            result = sync.observe(
                sample_time_s,
                100.010 + sample_time_s,
                frame_index=index + 1,
            )

        self.assertIs(result.status, ClockSyncStatus.READY)
        self.assertEqual(sync.sample_count, 51)
        self.assertLessEqual(sync.history_sample_count, 11)


if __name__ == "__main__":
    unittest.main()
