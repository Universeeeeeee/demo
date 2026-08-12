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
    led_health_changed = Signal(dict)

    def __init__(self, **_kwargs):
        super().__init__()
        self.stopped = False
        self.health_refreshes = 0

    @Slot()
    def connect_device(self):
        self.device_state_changed.emit("connected", "设备已连接")

    @Slot()
    def start_capture(self):
        self.device_state_changed.emit("streaming", "正在采集")

    @Slot()
    def refresh_led_health(self):
        self.health_refreshes += 1
        self.led_health_changed.emit(
            {
                "status": "normal",
                "sample_count": 64,
                "disconnected_leds": [],
                "flickering_leds": [],
            }
        )

    def stop(self):
        self.stopped = True
        self.device_state_changed.emit("disconnected", "设备已断开")


def test_ensure_device_connected_opens_device_without_config_or_capture(
    qtbot, monkeypatch
):
    monkeypatch.setattr(session_controller, "UsbWorker", _FakeUsbWorker)
    controller = session_controller.SessionController()
    started = QSignalSpy(controller.session_started)

    controller.ensure_device_connected()
    qtbot.waitUntil(lambda: controller.device_state == "connected")

    assert controller.config is None
    assert controller.engine is None
    assert not controller.is_running
    assert started.count() == 0
    controller.discard()


def test_connected_device_runs_one_automatic_led_health_sample(qtbot, monkeypatch):
    monkeypatch.setattr(session_controller, "UsbWorker", _FakeUsbWorker)
    controller = session_controller.SessionController()
    health = QSignalSpy(controller.led_health_changed)

    controller.ensure_device_connected()
    qtbot.waitUntil(lambda: health.count() == 1)

    assert health.at(0)[0]["status"] == "normal"
    assert controller._worker.health_refreshes == 1
    controller.discard()


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
    health_refreshes = controller._worker.health_refreshes
    controller.refresh_led_health()
    qtbot.wait(10)
    assert controller._worker.health_refreshes == health_refreshes
    controller.stop()
