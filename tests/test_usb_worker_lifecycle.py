"""USB lifecycle contract: connect first, capture only after consent."""

from __future__ import annotations

import hardware.usb_worker as usb_worker


class _FakeDll:
    def set_timeout(self, value):
        self.timeout = value


class _FakeDevice:
    def __init__(self, _dll_path):
        self.dll = _FakeDll()
        self.opened = False
        self.capture_started = False
        self.auto_read_started = False
        self.on_bytes = None
        self.on_frame = None

    def open(self, _vid, _pid):
        self.opened = True
        return True

    def start_capture(self):
        self.capture_started = True

    def set_on_bytes(self, callback):
        self.on_bytes = callback

    def set_on_frame(self, callback):
        self.on_frame = callback

    def start_auto_read(self, _chunk):
        self.auto_read_started = True
        return 0

    def stop_auto_read(self):
        self.auto_read_started = False

    def stop_capture(self):
        self.capture_started = False

    def close(self):
        self.opened = False


def test_connect_does_not_start_capture(monkeypatch):
    monkeypatch.setattr(usb_worker, "CyUsbInterfaceDevice", _FakeDevice)
    worker = usb_worker.UsbWorker(dll_path="fake")
    states = []
    worker.device_state_changed.connect(
        lambda state, message: states.append((state, message))
    )

    worker.connect_device()

    assert worker.dev.opened
    assert not worker.dev.capture_started
    assert not worker.dev.auto_read_started
    assert states[-1][0] == "connected"

    worker.start_capture()

    assert worker.dev.capture_started
    assert worker.dev.auto_read_started
    assert states[-1][0] == "streaming"
    worker.stop()


def test_connect_failure_emits_structured_error(monkeypatch):
    class _UnavailableDevice(_FakeDevice):
        def open(self, _vid, _pid):
            return False

    monkeypatch.setattr(usb_worker, "CyUsbInterfaceDevice", _UnavailableDevice)
    worker = usb_worker.UsbWorker(dll_path="fake")
    states = []
    worker.device_state_changed.connect(
        lambda state, message: states.append((state, message))
    )

    worker.connect_device()

    assert states[-1][0] == "error"
    assert "打开设备失败" in states[-1][1]
