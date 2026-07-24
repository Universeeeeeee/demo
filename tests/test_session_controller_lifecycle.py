"""Session controller two-stage lifecycle tests."""

from __future__ import annotations

from qtpy.QtCore import QObject, Signal, Slot
from qtpy.QtTest import QSignalSpy

import ui.session_controller as session_controller
from config.test_config import default_jump_config


class _FakeUsbWorker(QObject):
    raw_contact_signal = Signal(list, float)
    data_received = Signal(str)
    device_state_changed = Signal(str, str)

    def __init__(self, **_kwargs):
        super().__init__()
        self.stopped = False

    @Slot()
    def connect_device(self):
        self.device_state_changed.emit("connected", "设备已连接")

    @Slot()
    def start_capture(self):
        self.device_state_changed.emit("streaming", "正在采集")

    def stop(self):
        self.stopped = True
        self.device_state_changed.emit("disconnected", "设备已断开")


def test_prepare_connects_but_does_not_start_session(qtbot, monkeypatch):
    monkeypatch.setattr(session_controller, "UsbWorker", _FakeUsbWorker)
    controller = session_controller.SessionController()
    started = QSignalSpy(controller.session_started)

    controller.prepare(default_jump_config())
    qtbot.waitUntil(lambda: controller.device_state == "connected")

    assert not controller.is_running
    assert started.count() == 0

    controller.start()
    qtbot.waitUntil(lambda: controller.is_running)

    assert controller.device_state == "streaming"
    assert started.count() == 1
    controller.stop()
