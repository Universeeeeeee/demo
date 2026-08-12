"""Windows native title-bar styling regression tests."""

from __future__ import annotations

import ctypes

from ui.main_window import _apply_windows_dark_title_bar


class _FakeWindow:
    def __init__(self):
        self.win_id_calls = 0

    def winId(self):
        self.win_id_calls += 1
        return 1234


class _FakeDwmApi:
    def __init__(self, failures=()):
        self.failures = set(failures)
        self.calls = []

    def DwmSetWindowAttribute(self, hwnd, attribute, value_pointer, size):
        value = ctypes.cast(
            value_pointer, ctypes.POINTER(ctypes.c_int)
        ).contents.value
        self.calls.append((hwnd, attribute, value, size))
        return 1 if attribute in self.failures else 0


def test_non_windows_platform_does_not_create_native_window():
    window = _FakeWindow()

    applied = _apply_windows_dark_title_bar(
        window, platform_name="darwin", dwmapi=_FakeDwmApi()
    )

    assert not applied
    assert window.win_id_calls == 0


def test_windows_title_bar_uses_dark_mode_and_ui_colors():
    window = _FakeWindow()
    dwmapi = _FakeDwmApi()

    applied = _apply_windows_dark_title_bar(
        window, platform_name="win32", dwmapi=dwmapi
    )

    assert applied
    assert window.win_id_calls == 1
    assert [call[1] for call in dwmapi.calls] == [20, 35, 36]
    assert dwmapi.calls[0][2] == 1
    assert dwmapi.calls[1][2] == 0x0019110C
    assert dwmapi.calls[2][2] == 0x00FBF7F5


def test_windows_title_bar_falls_back_to_legacy_dark_attribute():
    window = _FakeWindow()
    dwmapi = _FakeDwmApi(failures={20})

    applied = _apply_windows_dark_title_bar(
        window, platform_name="win32", dwmapi=dwmapi
    )

    assert applied
    assert [call[1] for call in dwmapi.calls[:2]] == [20, 19]
