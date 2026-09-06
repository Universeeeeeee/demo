from qtpy.QtWidgets import QDialog

from data.subject_store import SubjectStore
from ui.views import setup_view as setup_view_module
from ui.views.setup_view import SetupView


def _subject_values(name: str, birth_year: int, team_id: int) -> dict:
    return {
        "display_name": name,
        "birth_year": birth_year,
        "height_cm": None,
        "weight_kg": None,
        "level": "intermediate",
        "focus_side": "",
        "team_ids": [team_id],
    }


def test_setup_new_subject_uses_selected_team(qtbot, tmp_path, monkeypatch):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    view = SetupView(store)
    qtbot.addWidget(view)
    monkeypatch.setattr(
        setup_view_module._SubjectDialog,
        "get_values",
        lambda *args, **kwargs: _subject_values("Alice", 1990, alpha_id),
    )

    view._on_new_subject_clicked()

    result = store.search_subjects("Alice")[0]
    assert [team.id for team in store.get_subject_teams(result.subject.id)] == [
        alpha_id
    ]


def test_setup_duplicate_can_reuse_existing_subject_in_another_team(
    qtbot, tmp_path, monkeypatch
):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    beta_id = store.create_team("Beta")
    subject_id = store.create_subject("Alice", 1990, team_id=alpha_id)
    view = SetupView(store)
    qtbot.addWidget(view)
    monkeypatch.setattr(
        setup_view_module._SubjectDialog,
        "get_values",
        lambda *args, **kwargs: _subject_values("Alice", 1990, beta_id),
    )

    class _ReuseDialog:
        action = "reuse"

        def __init__(self, matches, _parent):
            self._selected = matches[0]

        def exec_(self):
            return QDialog.Accepted

        def selected_result(self):
            return self._selected

    monkeypatch.setattr(setup_view_module, "_DuplicateSubjectDialog", _ReuseDialog)

    view._on_new_subject_clicked()

    assert len(store.find_duplicate_subjects("Alice", 1990)) == 1
    assert store.find_duplicate_subjects("Alice", 1990)[0].subject.id == subject_id
    assert {team.id for team in store.get_subject_teams(subject_id)} == {
        alpha_id,
        beta_id,
    }
