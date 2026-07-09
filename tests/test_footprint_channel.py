import pytest

pytest.importorskip("qtpy")

from qtpy.QtWidgets import QApplication

from ui.footprint_channel import FootprintChannelWidget, FootprintReplayPanel


def _app():
    return QApplication.instance() or QApplication([])


def test_channel_widget_maps_interface_side_zero_to_top():
    _app()
    widget = FootprintChannelWidget()

    widget.set_direction("Interface side")

    assert widget._y_for_index(0, 10, 90) == 10
    assert widget._y_for_index(95, 10, 90) == 100


def test_channel_widget_maps_opposite_side_zero_to_bottom():
    _app()
    widget = FootprintChannelWidget()

    widget.set_direction("Opposite side")

    assert widget._y_for_index(0, 10, 90) == 100
    assert widget._y_for_index(95, 10, 90) == 10


def test_replay_panel_applies_direction_to_channel():
    _app()
    panel = FootprintReplayPanel()

    panel.set_direction("Opposite side")

    assert panel._channel._y_for_index(0, 10, 90) == 100


def test_channel_widget_scales_footprint_size_from_real_foot_length():
    _app()
    widget = FootprintChannelWidget()

    foot_w, foot_h = widget._foot_size_for_lane(
        lane_width=900,
        lane_height=500,
        length_cm=24.0,
    )

    assert 110 <= foot_h <= 130
    assert 65 <= foot_w <= 80


def test_channel_widget_defaults_to_28cm_foot_length_when_missing():
    _app()
    widget = FootprintChannelWidget()

    foot_w, foot_h = widget._foot_size_for_lane(
        lane_width=900,
        lane_height=500,
        length_cm=None,
    )

    assert 135 <= foot_h <= 150
    assert 82 <= foot_w <= 92


def test_channel_widget_ignores_unreasonable_cluster_length_for_size():
    _app()
    widget = FootprintChannelWidget()

    default_size = widget._foot_size_for_lane(
        lane_width=900,
        lane_height=500,
        length_cm=None,
    )
    oversized_cluster_size = widget._foot_size_for_lane(
        lane_width=900,
        lane_height=500,
        length_cm=99.84,
    )

    assert oversized_cluster_size == default_size


def test_channel_widget_skips_candidate_foot_glyphs():
    _app()
    widget = FootprintChannelWidget()

    widget.render_state({
        "timestamp_s": 0.0,
        "contact_bits": [0] * 96,
        "feet": [
            {
                "contact_id": 1,
                "side": "unknown",
                "centroid_cm": 28.0,
                "length_cm": 99.84,
                "status": "candidate",
            },
            {
                "contact_id": 2,
                "side": "right",
                "centroid_cm": 42.0,
                "length_cm": 28.0,
                "status": "confirmed",
            },
        ],
    })

    assert len(widget._feet) == 1
    assert widget._feet[0]["contact_id"] == 2
    assert widget._feet[0]["side"] == "right"


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
        "feet": [{"contact_id": 1, "side": "left", "status": "confirmed"}],
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
