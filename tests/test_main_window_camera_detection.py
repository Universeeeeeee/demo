"""Main window Tiny SE camera detection tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ui.main_window as main_window


class _FakeControl:
    def __init__(self, _index: int) -> None:
        self.closed = False

    def init(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


class _FailingDShow:
    def __init__(self, **_kwargs) -> None:
        raise AssertionError("DShow detection should not be used when SDK is available")


class _SuccessfulDShow:
    created = False

    def __init__(self, **_kwargs) -> None:
        type(self).created = True
        self.closed = False

    def close(self) -> None:
        self.closed = True


class TinySeCameraDetectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._control_cls = main_window.TinySeCameraControl
        self._dshow_cls = main_window.TinySeDShowCapture
        _SuccessfulDShow.created = False

    def tearDown(self) -> None:
        main_window.TinySeCameraControl = self._control_cls
        main_window.TinySeDShowCapture = self._dshow_cls

    def test_sdk_detection_does_not_open_dshow_probe(self):
        main_window.TinySeCameraControl = _FakeControl
        main_window.TinySeDShowCapture = _FailingDShow

        self.assertTrue(main_window._detect_tinyse_camera())

    def test_dshow_probe_is_fallback_when_sdk_control_is_unavailable(self):
        main_window.TinySeCameraControl = None
        main_window.TinySeDShowCapture = _SuccessfulDShow

        self.assertTrue(main_window._detect_tinyse_camera())
        self.assertTrue(_SuccessfulDShow.created)


if __name__ == "__main__":
    unittest.main()
