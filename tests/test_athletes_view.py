"""Local athlete-management page tests."""

from __future__ import annotations

from qtpy.QtCore import Qt
from qtpy.QtTest import QSignalSpy

from data.subject_store import SubjectStore
from ui.views.athletes_view import AthletesView, _DuplicateSubjectDialog, _SubjectDialog


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


def test_athletes_view_displays_and_filters_active_team_memberships(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    beta_id = store.create_team("Beta")
    multi_team_id = store.create_subject("Alice", 1990, team_id=alpha_id)
    store.add_subject_to_team(multi_team_id, beta_id)
    store.create_subject("Bob", 1985)
    alpha_only_id = store.create_subject("Carol", 1995, team_id=alpha_id)
    view = AthletesView(store)
    qtbot.addWidget(view)

    teams_column = view._table.horizontalHeaderItem(5).text()
    assert teams_column == "所属团队"
    team_texts = {
        view._table.item(row, 0).text(): view._table.item(row, 5).text()
        for row in range(view._table.rowCount())
    }
    assert team_texts["Alice"] == "Alpha、Beta"
    assert team_texts["Bob"] == "未加入团队"

    view._team_filter.setCurrentIndex(view._team_filter.findData(alpha_id))
    assert {
        view._table.item(row, 0).text() for row in range(view._table.rowCount())
    } == {"Alice", "Carol"}

    view._team_filter.setCurrentIndex(view._team_filter.findData(view.WITHOUT_TEAM))
    assert [view._table.item(row, 0).text() for row in range(view._table.rowCount())] == [
        "Bob"
    ]
    assert alpha_only_id != multi_team_id


def test_subject_dialog_offers_initial_team_or_multi_team_memberships(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    beta_id = store.create_team("Beta")
    subject_id = store.create_subject("Alice", 1990, team_id=alpha_id)

    create_dialog = _SubjectDialog(store=store)
    qtbot.addWidget(create_dialog)
    assert [create_dialog._initial_team.itemText(index) for index in range(create_dialog._initial_team.count())] == [
        "暂不加入团队",
        "Alpha",
        "Beta",
        "新建团队…",
    ]
    assert create_dialog.values()["team_ids"] == []

    edit_dialog = _SubjectDialog(store=store, subject=store.get_subject(subject_id))
    qtbot.addWidget(edit_dialog)
    assert edit_dialog._team_list is not None
    selected = [
        edit_dialog._team_list.item(index).data(Qt.UserRole)
        for index in range(edit_dialog._team_list.count())
        if edit_dialog._team_list.item(index).checkState() == Qt.Checked
    ]
    assert selected == [alpha_id]


def test_subject_dialog_creates_and_selects_new_initial_team(qtbot, tmp_path, monkeypatch):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    dialog = _SubjectDialog(store=store)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        "ui.views.athletes_view.QInputDialog.getText",
        lambda *args: ("Gamma", True),
    )

    dialog._initial_team.setCurrentIndex(dialog._initial_team.count() - 1)
    dialog._handle_initial_team_choice()

    gamma = store.search_teams("Gamma")[0]
    assert dialog._initial_team.currentData() == gamma.id
    assert dialog.values()["team_ids"] == [gamma.id]


def test_edit_subject_synchronizes_active_team_memberships(qtbot, tmp_path, monkeypatch):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    beta_id = store.create_team("Beta")
    subject_id = store.create_subject("Alice", 1990, team_id=alpha_id)
    view = AthletesView(store)
    qtbot.addWidget(view)
    monkeypatch.setattr(
        _SubjectDialog,
        "get_values",
        classmethod(
            lambda cls, parent, subject=None, *, store=None: {
                "display_name": "Alice",
                "birth_year": 1990,
                "height_cm": None,
                "weight_kg": None,
                "level": "intermediate",
                "focus_side": "",
                "team_ids": [beta_id],
            }
        ),
    )

    view._edit_selected()

    assert [team.name for team in store.get_subject_teams(subject_id)] == ["Beta"]


def test_create_duplicate_flow_reuses_selected_profile_and_membership(qtbot, tmp_path, monkeypatch):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    beta_id = store.create_team("Beta")
    subject_id = store.create_subject("Alice", 1990, team_id=alpha_id)
    view = AthletesView(store)
    qtbot.addWidget(view)
    monkeypatch.setattr(
        view,
        "_ask_duplicate_action",
        lambda matches: ("reuse", matches[0]),
    )

    view._create_subject_from_values(
        {"display_name": "Alice", "birth_year": 1990, "team_ids": [beta_id]}
    )

    assert [result.subject.id for result in store.search_subjects()] == [subject_id]
    assert [team.name for team in store.get_subject_teams(subject_id)] == ["Alpha", "Beta"]


def test_create_duplicate_flow_reuses_existing_target_membership(qtbot, tmp_path, monkeypatch):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    subject_id = store.create_subject("Alice", 1990, team_id=alpha_id)
    view = AthletesView(store)
    qtbot.addWidget(view)
    monkeypatch.setattr(
        view,
        "_ask_duplicate_action",
        lambda matches: ("reuse", matches[0]),
    )

    view._create_subject_from_values(
        {"display_name": "Alice", "birth_year": 1990, "team_ids": [alpha_id]}
    )

    with store._connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM team_memberships WHERE subject_id = ? AND team_id = ?",
            (subject_id, alpha_id),
        ).fetchone()[0]
    assert count == 1


def test_create_without_duplicate_creates_selected_initial_team(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    view = AthletesView(store)
    qtbot.addWidget(view)

    view._create_subject_from_values(
        {"display_name": "Alice", "birth_year": 1990, "team_ids": [alpha_id]}
    )

    result = store.search_subjects()[0]
    assert [team.name for team in store.get_subject_teams(result.subject.id)] == ["Alpha"]


def test_create_duplicate_flow_can_create_second_profile_after_confirmation(
    qtbot, tmp_path, monkeypatch
):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    store.create_subject("Alice", 1990)
    view = AthletesView(store)
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_ask_duplicate_action", lambda matches: ("create", None))

    view._create_subject_from_values(
        {"display_name": "Alice", "birth_year": 1990, "team_ids": []}
    )

    assert len(store.find_duplicate_subjects("Alice", 1990)) == 2


def test_duplicate_dialog_displays_profile_details_without_database_id(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    store.create_subject("Alice", 1990, team_id=alpha_id)
    candidate = store.find_duplicate_subjects("Alice", 1990)[0]

    dialog = _DuplicateSubjectDialog([candidate])
    qtbot.addWidget(dialog)

    assert dialog._table.horizontalHeaderItem(0).text() == "姓名"
    assert dialog._table.horizontalHeaderItem(1).text() == "出生年份"
    assert dialog._table.horizontalHeaderItem(2).text() == "所属团队"
    assert dialog._table.horizontalHeaderItem(3).text() == "创建时间"
    assert dialog._table.horizontalHeaderItem(4).text() == "最近测试"
    assert "id" not in " ".join(
        dialog._table.item(0, column).text() for column in range(dialog._table.columnCount())
    ).casefold()
