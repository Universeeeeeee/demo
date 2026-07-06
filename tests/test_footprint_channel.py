import pytest

pytest.importorskip("qtpy")

from ui.footprint_channel import FootprintChannelWidget, FootprintReplayPanel


def test_channel_widget_accepts_short_frame_without_resizing(qtbot):
    widget = FootprintChannelWidget()
    qtbot.addWidget(widget)

    widget.render_state({"timestamp_s": 0.0, "contact_bits": [1, 0, 1], "feet": []})

    assert widget._contact_bits[:3] == [1, 0, 1]
    assert len(widget._contact_bits) == 96


def test_channel_widget_does_not_store_opacity_state(qtbot):
    widget = FootprintChannelWidget()
    qtbot.addWidget(widget)
    frame = {
        "timestamp_s": 0.0,
        "contact_bits": [0] * 96,
        "feet": [{"contact_id": 1, "side": "left", "status": "candidate"}],
    }

    widget.render_state(frame)

    assert "opacity" not in widget._feet[0]


def test_replay_panel_renders_first_timeline_frame(qtbot):
    panel = FootprintReplayPanel()
    qtbot.addWidget(panel)
    timeline = (
        {"timestamp_s": 0.0, "contact_bits": [0] * 96, "feet": []},
        {"timestamp_s": 0.1, "contact_bits": [1] * 96, "feet": []},
    )

    panel.set_timeline(timeline)

    assert panel._timeline == list(timeline)
    assert panel._channel._contact_bits == [0] * 96
