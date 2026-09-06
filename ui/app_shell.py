"""Application-level shell with fixed module navigation."""

from __future__ import annotations

import os

from qtpy.QtCore import Signal, Qt
from qtpy.QtGui import QPixmap
from qtpy.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from path_utils import get_base_dir


MODULE_ATHLETES = "athletes"
MODULE_TEST = "test"
MODULE_RESULTS = "results"
MODULE_SETTINGS = "settings"

MODULE_LABELS = {
    MODULE_ATHLETES: "运动员",
    MODULE_TEST: "测试",
    MODULE_RESULTS: "结果",
    MODULE_SETTINGS: "设置",
}

MODULE_GLYPHS = {
    MODULE_ATHLETES: "○",
    MODULE_TEST: "▷",
    MODULE_RESULTS: "▥",
    MODULE_SETTINGS: "⚙",
}


SHELL_QSS = """
QWidget#ApplicationShell {
    background: #0c1119;
    color: #e7ebf2;
    font-size: 13px;
}
QFrame#ApplicationSidebar {
    background: #0e141d;
    border-right: 1px solid #26303d;
}
QLabel#BrandLogo {
    background: transparent;
    border: none;
}
QPushButton#ModuleButton {
    min-height: 54px;
    padding: 0;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: #aeb7c5;
}
QPushButton#ModuleButton:hover {
    background: #151d28;
    color: #f4f6f9;
}
QPushButton#ModuleButton:checked {
    background: #171f2b;
    color: #ff8a1f;
    border-left-color: #ff7a00;
    font-weight: 650;
}
QLabel#NavGlyph {
    min-width: 25px;
    max-width: 25px;
    color: #aeb7c5;
    font-size: 20px;
    background: transparent;
}
QLabel#NavLabel {
    color: #aeb7c5;
    font-size: 15px;
    background: transparent;
}
QLabel#NavGlyph[active="true"],
QLabel#NavLabel[active="true"] {
    color: #ff8a1f;
    font-weight: 650;
}
QLabel#LocalModeNote {
    color: #697587;
    font-size: 12px;
}
QComboBox QAbstractItemView {
    background-color: #1a2230;
    color: #e7ebf2;
    selection-background-color: #34445a;
    selection-color: white;
}
QFrame#ShellContent {
    background: #0c1119;
    border: none;
}
"""

APP_DIALOG_QSS = """
QDialog,
QMessageBox,
QInputDialog {
    background-color: #121923;
    color: #e8edf5;
}
QDialog QLabel,
QMessageBox QLabel,
QInputDialog QLabel {
    color: #dfe5ee;
    background: transparent;
}
QDialog QLineEdit,
QDialog QComboBox,
QDialog QSpinBox,
QDialog QDoubleSpinBox {
    min-height: 34px;
    border: 1px solid #354151;
    border-radius: 6px;
    background-color: #1a2230;
    color: #e7ebf2;
    padding: 0 9px;
    selection-background-color: #ff7a00;
}
QDialog QComboBox::drop-down,
QDialog QSpinBox::up-button,
QDialog QSpinBox::down-button,
QDialog QDoubleSpinBox::up-button,
QDialog QDoubleSpinBox::down-button {
    width: 24px;
    border: none;
    background-color: #242e3c;
}
QDialog QAbstractItemView {
    background-color: #1a2230;
    color: #e7ebf2;
    border: 1px solid #354151;
    selection-background-color: #34445a;
}
QDialog QPushButton,
QMessageBox QPushButton {
    min-width: 80px;
    min-height: 34px;
    border: 1px solid #354151;
    border-radius: 6px;
    background-color: #1a2230;
    color: #e7ebf2;
    padding: 0 14px;
}
QDialog QPushButton:hover,
QMessageBox QPushButton:hover {
    background-color: #232d3c;
}
QDialog QPushButton:default,
QMessageBox QPushButton:default {
    background-color: #ff7a00;
    border-color: #ff7a00;
    color: white;
}
"""


class ApplicationSidebar(QFrame):
    """Fixed expanded navigation. Collapsing is intentionally deferred."""

    module_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ApplicationSidebar")
        self.setFixedWidth(184)
        self.buttons: dict[str, QPushButton] = {}
        self._active_module = MODULE_TEST
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 18, 10, 16)
        layout.setSpacing(10)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(8, 0, 4, 20)

        self.brand_logo = QLabel()
        self.brand_logo.setObjectName("BrandLogo")
        self.brand_logo.setAccessibleName("映衡")
        self.brand_logo.setFixedSize(146, 52)
        self.brand_logo.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        logo_path = os.path.join(
            get_base_dir(), "ui", "assets", "yingheng_brand.png"
        )
        logo = QPixmap(logo_path)
        self.brand_logo.setPixmap(
            logo.scaled(
                self.brand_logo.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )
        brand_row.addWidget(self.brand_logo)
        brand_row.addStretch()
        layout.addLayout(brand_row)

        for module in (
            MODULE_ATHLETES,
            MODULE_TEST,
            MODULE_RESULTS,
            MODULE_SETTINGS,
        ):
            button = QPushButton()
            button.setObjectName("ModuleButton")
            button.setMinimumHeight(54)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setAccessibleName(MODULE_LABELS[module])

            button_layout = QHBoxLayout(button)
            button_layout.setContentsMargins(16, 0, 10, 0)
            button_layout.setSpacing(13)

            glyph = QLabel(MODULE_GLYPHS[module])
            glyph.setObjectName("NavGlyph")
            glyph.setAlignment(Qt.AlignCenter)
            glyph.setAttribute(Qt.WA_TransparentForMouseEvents)
            glyph_font = glyph.font()
            glyph_font.setPixelSize(20)
            glyph.setFont(glyph_font)
            button_layout.addWidget(glyph)

            label = QLabel(MODULE_LABELS[module])
            label.setObjectName("NavLabel")
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            label_font = label.font()
            label_font.setPixelSize(15)
            label.setFont(label_font)
            button_layout.addWidget(label)
            button_layout.addStretch(1)

            button.clicked.connect(
                lambda _checked=False, key=module: self._request_module(key)
            )
            self._button_group.addButton(button)
            self.buttons[module] = button
            layout.addWidget(button)

        layout.addStretch(1)
        local_note = QLabel("本地模式 · 无需登录")
        local_note.setObjectName("LocalModeNote")
        local_note.setAlignment(Qt.AlignCenter)
        layout.addWidget(local_note)
        self.set_active_module(MODULE_TEST)

    def set_active_module(self, module: str) -> None:
        button = self.buttons.get(module)
        if button is not None:
            self._active_module = module
            for key, candidate in self.buttons.items():
                active = key == module
                candidate.setChecked(active)
                for object_name in ("NavGlyph", "NavLabel"):
                    label = candidate.findChild(QLabel, object_name)
                    if label is None:
                        continue
                    label.setProperty("active", active)
                    label.style().unpolish(label)
                    label.style().polish(label)

    def _request_module(self, module: str) -> None:
        # A route can be rejected by MainWindow (for example while acquiring).
        # Keep the accepted route selected until the router confirms a change.
        self.set_active_module(self._active_module)
        self.module_requested.emit(module)


class ApplicationShell(QWidget):
    """Visual shell; the main window remains authoritative for routing."""

    module_requested = Signal(str)

    def __init__(self, content: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("ApplicationShell")
        self.setStyleSheet(SHELL_QSS)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = ApplicationSidebar()
        self.sidebar.module_requested.connect(self.module_requested)
        layout.addWidget(self.sidebar)

        content_frame = QFrame()
        content_frame.setObjectName("ShellContent")
        content_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(content)
        layout.addWidget(content_frame, 1)

    def set_active_module(self, module: str) -> None:
        self.sidebar.set_active_module(module)
