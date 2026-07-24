"""Minimal local settings and diagnostics module."""

from __future__ import annotations

import os

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from data.subject_store import SubjectStore, default_db_path
from path_utils import find_dll


SETTINGS_QSS = """
QWidget#SettingsViewRoot {
    background: #0c1119;
    color: #e7ebf2;
}
QLabel#PageTitle {
    color: #f5f7fb;
    font-size: 20px;
    font-weight: 700;
}
QLabel#PageSubtitle {
    color: #8f9bad;
    font-size: 11px;
}
QLabel#ModeLabel {
    color: #8ecf78;
    background: #132219;
    border: 1px solid #294b32;
    border-radius: 7px;
    padding: 7px 11px;
    font-size: 11px;
}
QFrame#SettingsCard {
    background: #121923;
    border: 1px solid #293442;
    border-radius: 8px;
}
QLabel#CardTitle {
    color: #f0f3f7;
    font-size: 14px;
    font-weight: 700;
}
QLabel#FieldLabel {
    color: #8f9bad;
    font-size: 11px;
}
QLabel#FieldValue {
    color: #dce2eb;
    font-size: 11px;
}
QPushButton {
    min-height: 32px;
    border: 1px solid #354151;
    border-radius: 6px;
    background: #1a2230;
    color: #d9dee8;
    padding: 0 14px;
}
QPushButton:hover {
    background: #232d3c;
}
"""


class SettingsView(QWidget):
    """Read-only diagnostics until a persistent settings model exists."""

    def __init__(self, subject_store: SubjectStore | None = None, parent=None):
        super().__init__(parent)
        self._subject_store = subject_store
        self._value_labels: dict[str, QLabel] = {}
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.setObjectName("SettingsViewRoot")
        self.setStyleSheet(SETTINGS_QSS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 22)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(3)
        title = QLabel("设置")
        title.setObjectName("PageTitle")
        subtitle = QLabel("设备与本地系统诊断")
        subtitle.setObjectName("PageSubtitle")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header.addLayout(title_column)
        header.addStretch(1)
        self._mode_label = QLabel("● 本地存储 · 无需登录")
        self._mode_label.setObjectName("ModeLabel")
        header.addWidget(self._mode_label)
        layout.addLayout(header)

        cards = QHBoxLayout()
        cards.setSpacing(16)
        cards.addWidget(
            self._card(
                "设备连接参数",
                [
                    ("vid", "USB VID"),
                    ("pid", "USB PID"),
                    ("timeout", "读取超时"),
                    ("chunk", "读取块大小"),
                    ("dll", "设备 DLL"),
                ],
            ),
            1,
        )
        cards.addWidget(
            self._card(
                "本地数据",
                [
                    ("database", "SQLite 数据库"),
                    ("export", "默认导出目录"),
                    ("sampling", "标称采样率"),
                    ("cloud", "云同步"),
                ],
            ),
            1,
        )
        layout.addLayout(cards)
        layout.addStretch(1)

        refresh_row = QHBoxLayout()
        refresh_row.addStretch(1)
        refresh = QPushButton("刷新诊断信息")
        refresh.clicked.connect(self.refresh)
        refresh_row.addWidget(refresh)
        layout.addLayout(refresh_row)

    def _card(self, title: str, fields: list[tuple[str, str]]) -> QFrame:
        card = QFrame()
        card.setObjectName("SettingsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(14)
        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        card_layout.addWidget(title_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(13)
        for row, (key, label) in enumerate(fields):
            field_label = QLabel(label)
            field_label.setObjectName("FieldLabel")
            value_label = QLabel("—")
            value_label.setObjectName("FieldValue")
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value_label.setWordWrap(True)
            self._value_labels[key] = value_label
            grid.addWidget(field_label, row, 0)
            grid.addWidget(value_label, row, 1)
        grid.setColumnStretch(1, 1)
        card_layout.addLayout(grid)
        card_layout.addStretch(1)
        return card

    def refresh(self) -> None:
        vid = _parse_int_env("DAYU_VID", 0x04B4)
        pid = _parse_int_env("DAYU_PID", 0x1004)
        timeout = _parse_int_env("DAYU_TIMEOUT", 30)
        chunk = _parse_int_env("DAYU_CHUNK", 512)
        db_path = (
            self._subject_store.db_path
            if self._subject_store is not None
            else default_db_path()
        )
        self._value_labels["vid"].setText(f"0x{vid:04X}")
        self._value_labels["pid"].setText(f"0x{pid:04X}")
        self._value_labels["timeout"].setText(f"{timeout} ms（只读）")
        self._value_labels["chunk"].setText(f"{chunk} bytes（只读）")
        self._value_labels["dll"].setText(str(find_dll() or "未找到"))
        self._value_labels["database"].setText(str(db_path))
        self._value_labels["export"].setText(str(db_path.parent))
        self._value_labels["sampling"].setText("标称 1000 Hz（运行时未校验）")
        self._value_labels["cloud"].setText("未启用")


def _parse_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value, 0)
    except ValueError:
        return default
