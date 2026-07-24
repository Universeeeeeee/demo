"""Local athlete-management page tests."""

from __future__ import annotations

from qtpy.QtCore import Qt
from qtpy.QtTest import QSignalSpy

from data.subject_store import SubjectStore
from ui.views.athletes_view import AthletesView


def test_athletes_view_lists_searches_and_starts_test(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alice_id = store.create_subject("Alice", 1990)
    store.create_subject("Bob", 1985)
    view = AthletesView(store)
    qtbot.addWidget(view)

    assert view._table.rowCount() == 2

    view._search.setText("Alice")
    assert view._table.rowCount() == 1
    view._table.selectRow(0)

    spy = QSignalSpy(view.test_requested)
    qtbot.mouseClick(view._btn_test, Qt.LeftButton)

    assert spy.count() == 1
    assert spy.at(0)[0].subject.id == alice_id


def test_athletes_view_refreshes_after_external_subject_creation(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    view = AthletesView(store)
    qtbot.addWidget(view)

    assert view._table.rowCount() == 0
    store.create_subject("Carol", 1995)

    view.refresh()

    assert view._table.rowCount() == 1
    assert view._table.item(0, 0).text() == "Carol"
