"""Application-level navigation shell tests."""

from __future__ import annotations

from qtpy.QtCore import Qt
from qtpy.QtGui import QPalette
from qtpy.QtTest import QSignalSpy
from qtpy.QtWidgets import QApplication, QLabel

from ui.app_shell import (
    MODULE_ATHLETES,
    MODULE_RESULTS,
    MODULE_SETTINGS,
    MODULE_TEST,
    ApplicationShell,
)
from ui.views.athletes_view import AthletesView


def test_shell_has_fixed_application_navigation(qtbot):
    content = QLabel("content")
    shell = ApplicationShell(content)
    qtbot.addWidget(shell)

    assert shell.sidebar.width() == 184
    assert list(shell.sidebar.buttons) == [
        MODULE_ATHLETES,
        MODULE_TEST,
        MODULE_RESULTS,
        MODULE_SETTINGS,
    ]
    assert shell.sidebar.brand_logo.accessibleName() == "映衡"
    assert shell.sidebar.brand_logo.text() == ""
    assert not shell.sidebar.brand_logo.pixmap().isNull()
    assert shell.sidebar.findChild(QLabel, "BrandInitials") is None
    assert shell.sidebar.findChild(QLabel, "BrandName") is None
    assert shell.sidebar.buttons[MODULE_TEST].isChecked()


def test_shell_emits_route_without_switching_business_content(qtbot):
    shell = ApplicationShell(QLabel("content"))
    qtbot.addWidget(shell)
    spy = QSignalSpy(shell.module_requested)

    qtbot.mouseClick(shell.sidebar.buttons[MODULE_RESULTS], Qt.LeftButton)

    assert spy.count() == 1
    assert spy.at(0)[0] == MODULE_RESULTS
    assert shell.sidebar.buttons[MODULE_TEST].isChecked()

    shell.set_active_module(MODULE_RESULTS)
    assert shell.sidebar.buttons[MODULE_RESULTS].isChecked()
    assert not shell.sidebar.buttons[MODULE_TEST].isChecked()


def test_navigation_uses_larger_icons_labels_and_row_spacing(qtbot):
    shell = ApplicationShell(QLabel("content"))
    qtbot.addWidget(shell)
    shell.show()

    buttons = list(shell.sidebar.buttons.values())
    for button in buttons:
        glyph = button.findChild(QLabel, "NavGlyph")
        label = button.findChild(QLabel, "NavLabel")
        assert glyph is not None
        assert label is not None
        assert button.minimumHeight() >= 52
        assert glyph.font().pixelSize() >= 18
        assert label.font().pixelSize() >= 15

    assert shell.sidebar.buttons[MODULE_TEST].findChild(
        QLabel, "NavGlyph"
    ).property("active")
    assert not shell.sidebar.buttons[MODULE_RESULTS].findChild(
        QLabel, "NavGlyph"
    ).property("active")
    assert buttons[1].geometry().top() - buttons[0].geometry().bottom() >= 10


def test_shell_keeps_combo_popup_text_readable(qtbot):
    athletes = AthletesView(None)
    shell = ApplicationShell(athletes)
    qtbot.addWidget(shell)
    shell.show()
    QApplication.processEvents()

    popup_text = athletes._team_filter.view().palette().color(QPalette.Text)

    assert popup_text.lightness() > 160
