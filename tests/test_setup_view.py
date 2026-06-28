"""Tests for the setup view config summary."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qtpy.QtWidgets import QApplication

from config.treadmill_config import TreadmillGaitConfig
from ui.views.setup_view import SetupView


_APP = None


def _app():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
    else:
        _APP = app
    return _APP


def test_setup_view_accepts_treadmill_gait_config_without_attribute_error():
    _app()
    view = SetupView()
    config = TreadmillGaitConfig(
        stop_type="End of Time",
        test_length="05:00",
        treadmill_speed=5.5,
        direction="Interface side",
    )

    view._set_current_config(config, "manual")

    summary_text = view._summary_label.text()
    assert "跑步机步态" in summary_text
    assert "速度 5.5 km/h" in summary_text
    assert "方向 Interface side" in summary_text
    assert view.btn_ready.isEnabled()
