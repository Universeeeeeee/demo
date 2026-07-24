"""Application-level shell with fixed module navigation."""

from __future__ import annotations

from qtpy.QtCore import Signal, Qt
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
}
QFrame#ApplicationSidebar {
    background: #0e141d;
    border-right: 1px solid #26303d;
}
QFrame#BrandMark {
    background: #ff7a00;
    border: none;
    border-radius: 8px;
}
QLabel#BrandInitials {
    color: white;
    font-size: 15px;
    font-weight: 800;
}
QLabel#BrandName {
    color: #f5f7fb;
    font-size: 14px;
    font-weight: 700;
}
QPushButton#ModuleButton {
    min-height: 46px;
    padding: 0 12px;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: #aeb7c5;
    font-size: 13px;
    text-align: left;
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
    min-width: 22px;
    max-width: 22px;
    color: inherit;
}
QLabel#LocalModeNote {
    color: #697587;
    font-size: 10px;
}
QFrame#ShellContent {
    background: #0c1119;
    border: none;
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
        layout.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(8, 0, 4, 22)
        brand_row.setSpacing(10)

        brand_mark = QFrame()
        brand_mark.setObjectName("BrandMark")
        brand_mark.setFixedSize(38, 38)
        mark_layout = QVBoxLayout(brand_mark)
        mark_layout.setContentsMargins(0, 0, 0, 0)
        initials = QLabel("IJ")
        initials.setObjectName("BrandInitials")
        initials.setAlignment(Qt.AlignCenter)
        mark_layout.addWidget(initials)
        brand_row.addWidget(brand_mark)

        self.brand_name = QLabel("IronJump")
        self.brand_name.setObjectName("BrandName")
        brand_row.addWidget(self.brand_name)
        brand_row.addStretch()
        layout.addLayout(brand_row)

        for module in (
            MODULE_ATHLETES,
            MODULE_TEST,
            MODULE_RESULTS,
            MODULE_SETTINGS,
        ):
            button = QPushButton(
                f"  {MODULE_GLYPHS[module]}     {MODULE_LABELS[module]}"
            )
            button.setObjectName("ModuleButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
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
            button.setChecked(True)

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
