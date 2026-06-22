"""Tiny SE camera widget lifecycle tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from camera.tinyse_camera import TinySeCameraControl, TinySeCameraWidget


class _FakeCapture:
    is_recording = False

    def __init__(self) -> None:
        self.preview_states: list[bool] = []
        self.stop_called = False
        self.stop_record_called = False

    def set_preview_enabled(self, enabled: bool) -> None:
        self.preview_states.append(enabled)

    def stop(self) -> None:
        self.stop_called = True

    def stop_record(self) -> None:
        self.stop_record_called = True


class _FakeThread:
    def __init__(self) -> None:
        self.quit_called = False
        self.wait_called = False

    def quit(self) -> None:
        self.quit_called = True

    def wait(self, _timeout: int) -> bool:
        self.wait_called = True
        return True


class _FakeCombo:
    def __init__(self, value: int) -> None:
        self._value = value

    def currentData(self) -> int:
        return self._value


class _FakeControl:
    def __init__(self, ret: int = 0) -> None:
        self.ret = ret
        self.ai_modes: list[int] = []
        self.ai_off_calls = 0

    def set_ai_mode(self, mode: int) -> int:
        self.ai_modes.append(mode)
        return self.ret

    def set_ai_off(self) -> int:
        self.ai_off_calls += 1
        return self.ret


class _FakeControlDll:
    def __init__(self) -> None:
        self.close_calls = 0

    def obsbot_close(self) -> None:
        self.close_calls += 1


class TinySeCameraWidgetLifecycleTest(unittest.TestCase):
    def test_stop_preview_keeps_capture_thread_alive_for_fast_restart(self):
        capture = _FakeCapture()
        thread = _FakeThread()
        running_states: list[bool] = []
        widget = SimpleNamespace(
            _capture=capture,
            _thread=thread,
            _preview_start_time=1.0,
            _preview_active=True,
            _set_running=lambda running: running_states.append(running),
        )

        TinySeCameraWidget._on_stop(widget)

        self.assertEqual(capture.preview_states, [False])
        self.assertFalse(capture.stop_called)
        self.assertFalse(thread.quit_called)
        self.assertIs(widget._capture, capture)
        self.assertIs(widget._thread, thread)
        self.assertFalse(widget._preview_active)
        self.assertEqual(running_states, [False])

    def test_start_preview_reuses_existing_capture_thread(self):
        capture = _FakeCapture()
        thread = _FakeThread()
        running_states: list[bool] = []
        widget = SimpleNamespace(
            _capture=capture,
            _thread=thread,
            _preview_start_time=None,
            _preview_active=False,
            _set_running=lambda running: running_states.append(running),
        )

        TinySeCameraWidget._on_start(widget)

        self.assertEqual(capture.preview_states, [True])
        self.assertIsNotNone(widget._preview_start_time)
        self.assertTrue(widget._preview_active)
        self.assertEqual(running_states, [True])

    def test_ai_go_initializes_control_without_preview(self):
        control = _FakeControl()
        ensure_calls: list[bool] = []
        reports: list[tuple[str, int]] = []
        widget = SimpleNamespace(
            _control=None,
            _cmb_ai=_FakeCombo(4),
            _report_control_result=lambda action, ret: reports.append((action, ret)),
        )

        def ensure_control(apply_settings: bool = True) -> bool:
            ensure_calls.append(apply_settings)
            widget._control = control
            return True

        widget._ensure_control = ensure_control
        widget._ctl = lambda: widget._control

        TinySeCameraWidget._on_ai_go(widget)

        self.assertEqual(ensure_calls, [False])
        self.assertEqual(control.ai_modes, [4])
        self.assertEqual(reports, [("AI 追踪", 0)])

    def test_ai_off_initializes_control_and_reports_failure(self):
        control = _FakeControl(ret=-3)
        ensure_calls: list[bool] = []
        reports: list[tuple[str, int]] = []
        widget = SimpleNamespace(
            _control=None,
            _report_control_result=lambda action, ret: reports.append((action, ret)),
        )

        def ensure_control(apply_settings: bool = True) -> bool:
            ensure_calls.append(apply_settings)
            widget._control = control
            return True

        widget._ensure_control = ensure_control
        widget._ctl = lambda: widget._control

        TinySeCameraWidget._on_ai_off(widget)

        self.assertEqual(ensure_calls, [False])
        self.assertEqual(control.ai_off_calls, 1)
        self.assertEqual(reports, [("关闭 AI 追踪", -3)])

    def test_control_close_does_not_shutdown_process_sdk_singleton(self):
        control = object.__new__(TinySeCameraControl)
        dll = _FakeControlDll()
        control._dll = dll

        TinySeCameraControl.close(control)

        self.assertEqual(dll.close_calls, 0)
        self.assertIsNone(control._dll)


if __name__ == "__main__":
    unittest.main()
