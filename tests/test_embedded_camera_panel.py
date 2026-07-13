import pytest
import numpy as np

pytest.importorskip("dayu_widgets")

from ui.embedded_camera_panel import EmbeddedCameraPanel


def test_preview_area_keeps_sixteen_by_nine_ratio(qtbot):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel.resize(1200, 720)
    panel.show()
    qtbot.wait(10)

    assert panel._preview.width() * 9 == panel._preview.height() * 16
    content = panel._preview.contentsRect()
    assert content.width() * 9 == content.height() * 16


def test_preview_frame_fills_larger_sixteen_by_nine_area(qtbot):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel._preview.setGeometry(0, 0, 2048, 1152)
    panel._preview_active = True

    panel._on_frame(np.zeros((1080, 1920, 3), dtype=np.uint8))

    pixmap = panel._preview.pixmap()
    assert pixmap.width() == panel._preview.contentsRect().width()
    assert pixmap.height() == panel._preview.contentsRect().height()


def test_preview_uses_one_toggle_button(qtbot):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)

    panel._set_running(False)
    assert panel._btn_preview.text() == "Start Preview"

    panel._set_running(True)
    assert panel._btn_preview.text() == "Stop Preview"
    assert not hasattr(panel, "_btn_stop")


def test_preview_toggle_dispatches_current_state(qtbot, monkeypatch):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    calls = []
    monkeypatch.setattr(panel, "start_preview", lambda: calls.append("start"))
    monkeypatch.setattr(panel, "stop_preview", lambda: calls.append("stop"))

    panel._preview_active = False
    panel._toggle_preview()
    panel._preview_active = True
    panel._toggle_preview()

    assert calls == ["start", "stop"]


def test_tinyse_settings_include_existing_camera_controls(qtbot):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)

    assert panel._chk_mirror.text() == "镜像"
    assert panel._cmb_fov.count() == 3
    assert panel._cmb_ai.count() == 6
    assert panel._chk_af.text() == "自动对焦"
    assert panel._cmb_exp.count() == 19
    assert panel._cmb_flicker.count() == 2
    assert panel._cmb_wdr.count() == 3
    assert panel._record_action.text() == "Record"


def test_tinyse_default_settings_are_forwarded_to_control(qtbot):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)

    class Control:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            return lambda value: self.calls.append((name, value))

    control = Control()
    panel._apply_control_settings(control)

    assert control.calls == [
        ("set_fov", 0),
        ("set_auto_focus", True),
        ("set_exposure_compensation", 0),
        ("set_anti_flicker", 0),
        ("set_wdr", 0),
        ("set_ai_mode", 4),
    ]
