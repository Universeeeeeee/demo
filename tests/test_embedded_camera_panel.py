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


def test_default_preview_chrome_only_shows_settings_gear(qtbot):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel.resize(1200, 720)
    panel.show()
    qtbot.wait(10)

    assert not hasattr(panel, "_title")
    assert not hasattr(panel, "_stats")
    assert not hasattr(panel, "_btn_preview")
    assert panel._btn_settings.parent() is panel._preview_container
    assert panel._btn_settings.isVisible()
    assert panel._preview.geometry().contains(panel._btn_settings.geometry())


def test_restart_preview_action_restarts_capture(qtbot, monkeypatch):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    calls = []
    monkeypatch.setattr(panel, "shutdown", lambda: calls.append("shutdown"))
    monkeypatch.setattr(panel, "start_preview", lambda: calls.append("start"))

    panel._restart_action.trigger()

    assert panel._restart_action.text() == "重新启动预览"
    assert calls == ["shutdown", "start"]


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
