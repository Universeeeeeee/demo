import threading
import time
import unittest

from vision.foot_reference import (
    FootLabel,
    FootPoseSample,
    Landmark,
    VisionConfig,
)
from vision.mediapipe_pose import VisionUnavailableError
from vision.service import EventHook, FootVisionService


def _pose(timestamp_ms: int) -> FootPoseSample:
    left = Landmark(0.4, 0.91, 0.0, 0.99, 0.99)
    right = Landmark(0.6, 0.70, 0.0, 0.99, 0.99)
    return FootPoseSample(
        timestamp_ms / 1000.0,
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


class _FakeAdapter:
    def __init__(self, _model_path):
        self.opened = False
        self.closed = False
        self.timestamps = []

    def open(self):
        self.opened = True

    def infer_bgr(self, _frame, timestamp_ms):
        self.timestamps.append(timestamp_ms)
        return _pose(timestamp_ms)

    def close(self):
        self.closed = True


class _UnavailableAdapter(_FakeAdapter):
    def open(self):
        raise VisionUnavailableError("model unavailable")


class _BlockingAdapter(_FakeAdapter):
    gate = threading.Event()

    def open(self):
        self.gate.wait(1.0)
        super().open()


class VisionServiceTests(unittest.TestCase):
    def setUp(self):
        self.config = VisionConfig(
            pre_event_ms=100,
            post_event_ms=60,
            inference_interval_ms=20,
            decision_timeout_ms=200,
            max_events=4,
        )

    def test_event_hook_connect_emit_and_disconnect(self):
        hook = EventHook()
        calls = []
        hook.connect(calls.append)

        hook.emit("ready")
        hook.disconnect(calls.append)
        hook.emit("ignored")

        self.assertEqual(calls, ["ready"])

    def test_service_processes_frames_and_event_on_worker_thread(self):
        service = FootVisionService(
            self.config,
            "fake.task",
            adapter_factory=_FakeAdapter,
        )
        ready = threading.Event()
        decisions = []

        def on_decision(decision):
            decisions.append(decision)
            ready.set()

        service.decision_ready.connect(on_decision)
        service.start()
        for timestamp_ms in range(0, 301, 20):
            service.submit_frame(object(), timestamp_ms / 1000.0)
        service.submit_touch_event(9, 0.150)

        self.assertTrue(ready.wait(1.0))
        service.stop()

        self.assertEqual(decisions[0].event_id, 9)
        self.assertEqual(decisions[0].event_time_s, 0.150)
        self.assertEqual(decisions[0].label, FootLabel.LEFT)
        self.assertFalse(service.is_running)

    def test_unavailable_model_returns_unknown_without_crashing(self):
        service = FootVisionService(
            self.config,
            "missing.task",
            adapter_factory=_UnavailableAdapter,
        )
        ready = threading.Event()
        decisions = []
        service.decision_ready.connect(lambda item: (decisions.append(item), ready.set()))

        service.start()
        service.submit_touch_event(2, time.perf_counter())

        self.assertTrue(ready.wait(1.0))
        service.stop()
        self.assertEqual(decisions[0].label, FootLabel.UNKNOWN)
        self.assertEqual(decisions[0].reason, "model_unavailable")

    def test_event_input_queue_is_bounded(self):
        _BlockingAdapter.gate.clear()
        config = VisionConfig(max_events=1)
        service = FootVisionService(
            config,
            "fake.task",
            adapter_factory=_BlockingAdapter,
        )
        decisions = []
        service.decision_ready.connect(decisions.append)
        service.start()

        service.submit_touch_event(1, time.perf_counter())
        service.submit_touch_event(2, time.perf_counter())

        self.assertEqual(decisions[0].reason, "event_queue_full")
        _BlockingAdapter.gate.set()
        service.stop()

    def test_stop_is_repeatable_and_closes_adapter(self):
        adapters = []

        def factory(path):
            adapter = _FakeAdapter(path)
            adapters.append(adapter)
            return adapter

        service = FootVisionService(self.config, "fake.task", adapter_factory=factory)
        service.start()
        deadline = time.time() + 1.0
        while not adapters or not adapters[0].opened:
            self.assertLess(time.time(), deadline)
            time.sleep(0.005)

        service.stop()
        service.stop()

        self.assertTrue(adapters[0].closed)


if __name__ == "__main__":
    unittest.main()
