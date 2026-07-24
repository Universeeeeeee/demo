"""Local athlete-management module."""

from __future__ import annotations

import logging
from datetime import datetime

from qtpy.QtCore import Signal, Qt
from qtpy.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from data.subject_store import SubjectProfile, SubjectSearchResult, SubjectStore


log = logging.getLogger(__name__)


ATHLETES_QSS = """
QWidget#AthletesViewRoot {
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
QFrame#AthleteToolbar,
QFrame#AthleteTableCard {
    background: #121923;
    border: 1px solid #293442;
    border-radius: 8px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 32px;
    border: 1px solid #354151;
    border-radius: 6px;
    background: #1a2230;
    color: #e7ebf2;
    padding: 0 9px;
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
QPushButton#PrimaryButton {
    background: #ff7a00;
    border-color: #ff7a00;
    color: white;
    font-weight: 650;
}
QTableWidget {
    background: #121923;
    alternate-background-color: #151d28;
    color: #dfe5ee;
    border: none;
    gridline-color: #26313f;
    selection-background-color: #273446;
    selection-color: white;
}
QHeaderView::section {
    background: #171f2b;
    color: #9da8b8;
    border: none;
    border-bottom: 1px solid #2b3543;
    padding: 8px;
}
"""


class AthletesView(QWidget):
    """Search and maintain athletes stored in the local SQLite database."""

    test_requested = Signal(object)  # SubjectSearchResult
    results_requested = Signal(object)  # SubjectSearchResult

    def __init__(self, subject_store: SubjectStore | None, parent=None):
        super().__init__(parent)
        self._subject_store = subject_store
        self._results: list[SubjectSearchResult] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.setObjectName("AthletesViewRoot")
        self.setStyleSheet(ATHLETES_QSS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 22)
        layout.setSpacing(16)

        title = QLabel("运动员")
        title.setObjectName("PageTitle")
        subtitle = QLabel("管理保存在本机的运动员档案和测试入口")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        toolbar = QFrame()
        toolbar.setObjectName("AthleteToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索运动员姓名")
        self._search.textChanged.connect(self.refresh)
        toolbar_layout.addWidget(self._search, 1)

        self._btn_new = QPushButton("新建运动员")
        self._btn_new.setObjectName("PrimaryButton")
        self._btn_new.clicked.connect(self._create_subject)
        toolbar_layout.addWidget(self._btn_new)

        self._btn_edit = QPushButton("编辑")
        self._btn_edit.clicked.connect(self._edit_selected)
        toolbar_layout.addWidget(self._btn_edit)

        self._btn_archive = QPushButton("归档")
        self._btn_archive.clicked.connect(self._archive_selected)
        toolbar_layout.addWidget(self._btn_archive)
        layout.addWidget(toolbar)

        table_card = QFrame()
        table_card.setObjectName("AthleteTableCard")
        card_layout = QVBoxLayout(table_card)
        card_layout.setContentsMargins(1, 1, 1, 12)
        card_layout.setSpacing(10)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["姓名", "年龄", "身高 / 体重", "训练水平", "训练侧重", "最近测试"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.itemSelectionChanged.connect(self._sync_actions)
        self._table.itemDoubleClicked.connect(lambda _item: self._start_selected_test())
        card_layout.addWidget(self._table, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(12, 0, 12, 0)
        actions.addStretch(1)
        self._btn_results = QPushButton("查看结果")
        self._btn_results.clicked.connect(self._show_selected_results)
        actions.addWidget(self._btn_results)
        self._btn_test = QPushButton("使用该运动员测试")
        self._btn_test.setObjectName("PrimaryButton")
        self._btn_test.clicked.connect(self._start_selected_test)
        actions.addWidget(self._btn_test)
        card_layout.addLayout(actions)
        layout.addWidget(table_card, 1)
        self._sync_actions()

    def refresh(self, _query: str | None = None) -> None:
        selected_id = None
        selected = self._selected_result()
        if selected is not None:
            selected_id = selected.subject.id

        if self._subject_store is None:
            self._results = []
        else:
            try:
                self._results = self._subject_store.search_subjects(
                    self._search.text().strip()
                )
            except Exception:
                log.exception("Failed to refresh athlete list")
                self._results = []

        self._table.setRowCount(0)
        selected_row = -1
        current_year = datetime.now().year
        focus_labels = {
            "": "均衡",
            "left": "左侧",
            "right": "右侧",
            "both": "双侧",
        }
        for row, result in enumerate(self._results):
            subject = result.subject
            self._table.insertRow(row)
            measurements = _measurement_text(subject)
            values = [
                subject.display_name,
                str(max(0, current_year - subject.birth_year)),
                measurements,
                subject.level,
                focus_labels.get(subject.focus_side, subject.focus_side),
                result.last_session_at[:16] if result.last_session_at else "暂无",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, result)
                self._table.setItem(row, column, item)
            if subject.id == selected_id:
                selected_row = row

        if selected_row >= 0:
            self._table.selectRow(selected_row)
        elif self._results:
            self._table.selectRow(0)
        self._sync_actions()

    def _selected_result(self) -> SubjectSearchResult | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return value if isinstance(value, SubjectSearchResult) else None

    def _sync_actions(self) -> None:
        enabled = self._selected_result() is not None
        self._btn_edit.setEnabled(enabled)
        self._btn_archive.setEnabled(enabled)
        self._btn_results.setEnabled(enabled)
        self._btn_test.setEnabled(enabled)

    def _create_subject(self) -> None:
        if self._subject_store is None:
            return
        values = _SubjectDialog.get_values(self)
        if values is None:
            return
        try:
            self._subject_store.create_subject(**values)
        except Exception as exc:
            QMessageBox.warning(self, "新建运动员", f"保存失败：{exc}")
            return
        self._search.clear()
        self.refresh()

    def _edit_selected(self) -> None:
        if self._subject_store is None:
            return
        result = self._selected_result()
        if result is None:
            return
        values = _SubjectDialog.get_values(self, result.subject)
        if values is None:
            return
        try:
            self._subject_store.update_subject(result.subject.id, **values)
        except Exception as exc:
            QMessageBox.warning(self, "编辑运动员", f"保存失败：{exc}")
            return
        self.refresh()

    def _archive_selected(self) -> None:
        if self._subject_store is None:
            return
        result = self._selected_result()
        if result is None:
            return
        answer = QMessageBox.question(
            self,
            "归档运动员",
            f"归档“{result.subject.display_name}”？历史测试不会删除。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._subject_store.archive_subject(result.subject.id)
        self.refresh()

    def _start_selected_test(self) -> None:
        result = self._selected_result()
        if result is not None:
            self.test_requested.emit(result)

    def _show_selected_results(self) -> None:
        result = self._selected_result()
        if result is not None:
            self.results_requested.emit(result)


class _SubjectDialog(QDialog):
    def __init__(self, subject: SubjectProfile | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑运动员" if subject else "新建运动员")
        form = QFormLayout(self)

        self.name = QLineEdit(subject.display_name if subject else "")
        self.birth_year = QSpinBox()
        self.birth_year.setRange(1900, datetime.now().year)
        self.birth_year.setValue(subject.birth_year if subject else 1990)
        self.height = QDoubleSpinBox()
        self.height.setRange(0, 250)
        self.height.setSuffix(" cm")
        self.height.setValue(float(subject.height_cm or 0.0) if subject else 0.0)
        self.weight = QDoubleSpinBox()
        self.weight.setRange(0, 300)
        self.weight.setSuffix(" kg")
        self.weight.setValue(float(subject.weight_kg or 0.0) if subject else 0.0)
        self.level = QComboBox()
        self.level.addItems(["beginner", "intermediate", "advanced"])
        self.level.setCurrentText(subject.level if subject else "intermediate")
        self.focus = QComboBox()
        self.focus.addItem("均衡", "")
        self.focus.addItem("左侧", "left")
        self.focus.addItem("右侧", "right")
        self.focus.addItem("双侧", "both")
        if subject:
            self.focus.setCurrentIndex(max(self.focus.findData(subject.focus_side), 0))

        form.addRow("姓名", self.name)
        form.addRow("出生年份", self.birth_year)
        form.addRow("身高", self.height)
        form.addRow("体重", self.weight)
        form.addRow("训练水平", self.level)
        form.addRow("训练侧重", self.focus)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept_if_valid(self) -> None:
        if not self.name.text().strip():
            QMessageBox.information(self, self.windowTitle(), "姓名不能为空。")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "display_name": self.name.text().strip(),
            "birth_year": self.birth_year.value(),
            "height_cm": self.height.value() or None,
            "weight_kg": self.weight.value() or None,
            "level": self.level.currentText(),
            "focus_side": self.focus.currentData() or "",
        }

    @classmethod
    def get_values(
        cls, parent: QWidget, subject: SubjectProfile | None = None
    ) -> dict | None:
        dialog = cls(subject, parent)
        if dialog.exec_() != QDialog.Accepted:
            return None
        return dialog.values()


def _measurement_text(subject: SubjectProfile) -> str:
    height = f"{subject.height_cm:g} cm" if subject.height_cm else "身高未填"
    weight = f"{subject.weight_kg:g} kg" if subject.weight_kg else "体重未填"
    return f"{height} / {weight}"
