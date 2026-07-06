"""Shared footprint-channel visualization widgets."""

from __future__ import annotations

import os

from qtpy.QtCore import Qt, QTimer
from qtpy.QtGui import QColor, QPainter, QPixmap
from qtpy.QtWidgets import QFrame, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from dayu_widgets.push_button import MPushButton

from path_utils import get_base_dir


_LED_COUNT = 96
_LED_SPACING_CM = 1.04

_SOURCE_IN = getattr(QPainter, "CompositionMode_SourceIn", None)
if _SOURCE_IN is None:
    _SOURCE_IN = QPainter.CompositionMode.CompositionMode_SourceIn


class FootprintChannelWidget(QFrame):
    """Render canonical footprint frames between two 96-LED rails."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._contact_bits = [0] * _LED_COUNT
        self._feet: list[dict] = []
        self._left_foot = self._load_pixmap("left_foot.png")
        self._right_foot = self._load_pixmap("right_foot.png")
        self.setMinimumSize(260, 420)
        self.setStyleSheet(
            "FootprintChannelWidget {"
            "  background-color: rgba(20, 20, 24, 0.9);"
            "  border: 1px solid rgba(90, 90, 95, 0.7);"
            "  border-radius: 8px;"
            "}"
        )

    def _load_pixmap(self, name: str) -> QPixmap:
        path = os.path.join(get_base_dir(), "ui", "assets", name)
        return QPixmap(path)

    def clear(self):
        self._contact_bits = [0] * _LED_COUNT
        self._feet = []
        self.update()

    def render_state(self, frame):
        if hasattr(frame, "to_dict"):
            frame = frame.to_dict()

        bits = [1 if int(bit) else 0 for bit in frame.get("contact_bits", [])[:_LED_COUNT]]
        if len(bits) < _LED_COUNT:
            bits.extend([0] * (_LED_COUNT - len(bits)))

        self._contact_bits = bits
        self._feet = [
            {key: value for key, value in dict(foot).items() if key != "opacity"}
            for foot in frame.get("feet", [])
        ]
        self.update()

    def _y_for_index(self, index: float, top: int, height: int) -> float:
        clamped = min(max(float(index), 0.0), float(_LED_COUNT - 1))
        return top + (clamped / float(_LED_COUNT - 1)) * height

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(14, 14, -14, -14)
        rail_left_x = rect.left() + 12
        rail_right_x = rect.right() - 12
        lane_left = rail_left_x + 22
        lane_right = rail_right_x - 22
        top = rect.top() + 20
        height = rect.height() - 40

        painter.setPen(QColor(70, 70, 76))
        painter.setBrush(QColor(28, 28, 32))
        painter.drawRoundedRect(lane_left, top, lane_right - lane_left, height, 8, 8)

        for idx, active in enumerate(self._contact_bits):
            y = self._y_for_index(idx, top, height)
            color = QColor(70, 220, 125) if active else QColor(70, 70, 76)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rail_left_x - 3, int(y) - 2, 6, 4, 2, 2)
            painter.drawRoundedRect(rail_right_x - 3, int(y) - 2, 6, 4, 2, 2)
            if active:
                painter.setPen(QColor(70, 220, 125, 60))
                painter.drawLine(lane_left, int(y), lane_right, int(y))

        for foot in self._feet:
            self._paint_foot(painter, foot, lane_left, lane_right, top, height)

    def _paint_foot(
        self,
        painter: QPainter,
        foot: dict,
        lane_left: int,
        lane_right: int,
        top: int,
        height: int,
    ):
        centroid_cm = foot.get("centroid_cm")
        if centroid_cm is None:
            return

        index = float(centroid_cm) / _LED_SPACING_CM
        y = self._y_for_index(index, top, height)
        side = foot.get("side", "unknown")
        status = foot.get("status", "confirmed")
        alpha = 255 if status == "confirmed" else 130
        color = (
            QColor(82, 170, 255, alpha)
            if side == "right"
            else QColor(82, 220, 130, alpha)
        )
        pixmap = self._right_foot if side == "right" else self._left_foot
        foot_w = max(42, int((lane_right - lane_left) * 0.34))
        foot_h = int(foot_w * 1.62)
        x_center = lane_left + (lane_right - lane_left) * (
            0.64 if side == "right" else 0.36
        )
        target_x = int(x_center - foot_w / 2)
        target_y = int(y - foot_h / 2)

        if pixmap.isNull():
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(target_x, target_y, foot_w, foot_h)
            return

        tinted = QPixmap(pixmap.size())
        tinted.fill(Qt.transparent)
        tint_painter = QPainter(tinted)
        tint_painter.drawPixmap(0, 0, pixmap)
        tint_painter.setCompositionMode(_SOURCE_IN)
        tint_painter.fillRect(tinted.rect(), color)
        tint_painter.end()
        painter.drawPixmap(target_x, target_y, foot_w, foot_h, tinted)


class FootprintReplayPanel(QWidget):
    """Replay a canonical footprint timeline through the shared channel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timeline: list = []
        self._index = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._channel = FootprintChannelWidget()
        layout.addWidget(self._channel, 1)

        controls = QHBoxLayout()
        self._btn_play = MPushButton("Play")
        self._btn_play.clicked.connect(self._toggle_playback)
        controls.addWidget(self._btn_play)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.valueChanged.connect(self._on_slider_changed)
        controls.addWidget(self._slider, 1)

        self._time_label = QLabel("0.000 s")
        controls.addWidget(self._time_label)
        layout.addLayout(controls)

    def set_timeline(self, timeline):
        self._timer.stop()
        self._btn_play.setText("Play")
        self._timeline = [
            frame.to_dict() if hasattr(frame, "to_dict") else frame
            for frame in timeline
        ]
        self._index = 0
        self._slider.setMaximum(max(len(self._timeline) - 1, 0))
        self._slider.setValue(0)

        if self._timeline:
            self._render_index(0)
        else:
            self._channel.clear()
            self._time_label.setText("No replay data")

    def _toggle_playback(self):
        if not self._timeline:
            return
        if self._timer.isActive():
            self._timer.stop()
            self._btn_play.setText("Play")
        else:
            self._timer.start(40)
            self._btn_play.setText("Pause")

    def _advance(self):
        if not self._timeline:
            self._timer.stop()
            return

        next_index = self._index + 1
        if next_index >= len(self._timeline):
            self._timer.stop()
            self._btn_play.setText("Play")
            return
        self._slider.setValue(next_index)

    def _on_slider_changed(self, value: int):
        if self._timeline:
            self._render_index(value)

    def _render_index(self, index: int):
        self._index = max(0, min(index, len(self._timeline) - 1))
        frame = self._timeline[self._index]
        self._channel.render_state(frame)
        self._time_label.setText(f"{frame.get('timestamp_s', 0.0):.3f} s")
