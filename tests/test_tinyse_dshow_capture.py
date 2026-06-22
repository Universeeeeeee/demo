"""Tiny SE DirectShow wrapper lifecycle tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
