"""Tiny SE DirectShow wrapper lifecycle tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from camera import tinyse_dshow_capture
from camera.tinyse_dshow_capture import TinySeDShowCapture


class _FakeDShowDll:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def tinyse_capture_stop(self, handle):
        self.calls.append(("stop", handle))
        return 0

    def tinyse_capture_destroy(self, handle):
        self.calls.append(("destroy", handle))


class TinySeDShowCaptureLifecycleTest(unittest.TestCase):
    def test_timed_callback_records_clock_before_copying_mjpeg_buffer(self):
        order = []
        calls = []

        def copy_buffer(_data, length):
            order.append("copy")
            return b"jpeg"[:length]

        def on_timed_frame(data, frame_index, sample_time_s, callback_time_s):
            order.append("callback")
            calls.append((data, frame_index, sample_time_s, callback_time_s))

        with (
            patch.object(
                tinyse_dshow_capture.time,
                "perf_counter",
                side_effect=lambda: order.append("clock") or 100.0,
            ),
            patch.object(tinyse_dshow_capture.ctypes, "string_at", copy_buffer),
        ):
            tinyse_dshow_capture._deliver_frame(
                object(),
                4,
                7,
                1.25,
                on_frame=None,
                on_timed_frame=on_timed_frame,
            )

        self.assertEqual(order, ["clock", "copy", "callback"])
        self.assertEqual(calls, [(b"jpeg", 7, 1.25, 100.0)])

    def test_legacy_callback_keeps_three_argument_signature(self):
        calls = []

        with (
            patch.object(tinyse_dshow_capture.time, "perf_counter", return_value=100.0),
            patch.object(tinyse_dshow_capture.ctypes, "string_at", return_value=b"jpeg"),
        ):
            tinyse_dshow_capture._deliver_frame(
                object(),
                4,
                7,
                1.25,
                on_frame=lambda *args: calls.append(args),
                on_timed_frame=None,
            )

        self.assertEqual(calls, [(b"jpeg", 7, 1.25)])

    def test_close_stops_started_capture_with_original_handle_before_destroy(self):
        capture = object.__new__(TinySeDShowCapture)
        dll = _FakeDShowDll()
        capture._dll = dll
        capture._handle = 1234
        capture._started = True

        capture.close()

        self.assertEqual(dll.calls, [("stop", 1234), ("destroy", 1234)])
        self.assertIsNone(capture._handle)
        self.assertFalse(capture._started)


if __name__ == "__main__":
    unittest.main()
