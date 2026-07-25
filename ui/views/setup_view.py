"""
setup_view.py — 测试配置页

复用现有 ParamPanel，提供配置摘要和"准备就绪"按钮。
用户确认配置后，发射 ready_signal(SessionSetup) 通知 MainWindow。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from qtpy.QtCore import Signal, Qt
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QScrollArea, QFrame,
    QSizePolicy, QLineEdit, QComboBox, QDialog, QDialogButtonBox,
    QLabel, QMessageBox, QPushButton, QSpinBox, QStackedWidget, QMenu,
)

from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton

from config.config_validation import validate_runtime_config
from config.test_config import AnyTestConfig
from data.subject_store import SubjectProfile, SubjectSearchResult, SubjectStore
from ui.views.agent_config_panel import AgentConfigPanel
from ui.param_panel import ParamPanel


log = logging.getLogger(__name__)


SETUP_QSS = """
QWidget#SetupViewRoot {
  background-color: #0c1119;
  color: #e8edf5;
}
QFrame#TopSubjectBar,
QFrame#ModeBar,
QFrame#ConfigWorkArea,
QFrame#ConfigSummaryCard {
  background-color: #121923;
  border: 1px solid #293442;
  border-radius: 8px;
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
QLabel#SummaryTitle {
  color: #f2f5f9;
  font-size: 15px;
  font-weight: 700;
}
QLabel#SummaryState {
  color: #ff9a3d;
  font-size: 12px;
  font-weight: 600;
}
QLabel#SummaryText {
  color: #c7cfdb;
  font-size: 13px;
}
QLabel#SummaryHint {
  color: #7f8a9a;
  font-size: 11px;
}
QLineEdit, QComboBox {
  min-height: 32px;
  border-radius: 6px;
  border: 1px solid #354151;
  background-color: #1a2230;
  color: #e7ebf2;
  padding: 0 10px;
}
QPushButton {
  min-height: 32px;
  border-radius: 6px;
  border: 1px solid #354151;
  background-color: #1a2230;
  color: #d9dee8;
  padding: 0 16px;
}
QPushButton:hover {
  background-color: #232d3c;
}
QPushButton#SubjectPrimaryButton,
QPushButton#PrimaryStartButton,
QPushButton#SegmentButton:checked {
  background-color: #ff7a00;
  border-color: #ff7a00;
  color: white;
}
QPushButton#PrimaryStartButton {
  min-height: 46px;
  font-size: 14px;
  font-weight: 700;
  border-radius: 7px;
}
QPushButton#PrimaryStartButton:disabled {
  background-color: #242c37;
  border-color: #303946;
  color: #6f7a89;
}
QPushButton#SegmentButton {
  min-width: 112px;
  border: none;
  background-color: transparent;
  font-weight: 600;
}
QPushButton#SegmentButton:hover {
  background-color: rgba(255, 255, 255, 0.05);
}
QMenu {
  background-color: #242936;
  color: #e7ebf2;
  border: 1px solid rgba(105, 115, 135, 0.38);
  padding: 6px;
}
QMenu::item {
  padding: 8px 22px;
  border-radius: 5px;
}
QMenu::item:selected {
  background-color: rgba(255, 133, 15, 0.22);
}
QScrollArea#ManualConfigScroll,
QScrollArea#ManualConfigScroll QWidget#qt_scrollarea_viewport {
  background: #121923;
  border: none;
}
"""

NEW_SUBJECT_DIALOG_QSS = """
QDialog#NewSubjectDialog {
  background-color: #121923;
  color: #e8edf5;
}
QDialog#NewSubjectDialog QLabel {
  color: #dfe5ee;
  font-size: 12px;
}
QDialog#NewSubjectDialog QLineEdit,
QDialog#NewSubjectDialog QComboBox,
QDialog#NewSubjectDialog QSpinBox {
  min-height: 34px;
  border-radius: 6px;
  border: 1px solid #354151;
  background-color: #1a2230;
  color: #e7ebf2;
  padding: 0 10px;
  selection-background-color: #ff7a00;
}
QDialog#NewSubjectDialog QComboBox::drop-down,
QDialog#NewSubjectDialog QSpinBox::up-button,
QDialog#NewSubjectDialog QSpinBox::down-button {
  border: none;
  background-color: #242e3c;
  width: 24px;
}
QDialog#NewSubjectDialog QPushButton {
  min-width: 80px;
  min-height: 34px;
  border-radius: 6px;
  border: 1px solid #354151;
  background-color: #1a2230;
  color: #e7ebf2;
  padding: 0 14px;
}
QDialog#NewSubjectDialog QPushButton:hover {
  background-color: #232d3c;
}
QDialog#NewSubjectDialog QPushButton:default {
  background-color: #ff7a00;
  border-color: #ff7a00;
  color: white;
}
"""


@dataclass(frozen=True)
class SessionSetup:
    config: AnyTestConfig
    subject_id: int | None = None
    subject: SubjectProfile | None = None
    subject_snapshot: dict | None = None
    config_source: str | None = None


class SetupView(QWidget):
    """测试配置视图 — 参数面板 + 配置摘要 + 准备就绪按钮。"""

    ready_signal = Signal(object)  # SessionSetup
    history_requested = Signal(object)  # SubjectSearchResult | None

    def __init__(self, subject_store: SubjectStore | None = None,
                 llm_client=None, parent=None):
        super().__init__(parent)
        self._llm_client = llm_client
        self._subject_store = subject_store
        self._subject_search = None
        self._subject_combo = None
        self._action_load_last_config = None
        self._action_history = None
        self._current_config: AnyTestConfig | None = None
        self._config_source: str | None = None
        self._config_errors: list[str] = []
        self._config_mode_index = 0
        self._syncing_config_to_panel = False
        self._build_ui()

    def _build_ui(self):
        self.setObjectName("SetupViewRoot")
        self.setStyleSheet(SETUP_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 22)
        layout.setSpacing(16)

        # ===== 页面标题 =====
        header = QHBoxLayout()
        header.setSpacing(12)
        title_column = QVBoxLayout()
        title_column.setSpacing(3)
        title = QLabel("测试")
        title.setObjectName("PageTitle")
        subtitle = QLabel("配置测试参数并连接设备")
        subtitle.setObjectName("PageSubtitle")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header.addLayout(title_column)
        header.addStretch(1)
        layout.addLayout(header)

        workspace = QHBoxLayout()
        workspace.setSpacing(16)

        # ===== 左侧配置工作区 =====
        config_area = QFrame()
        config_area.setObjectName("ConfigWorkArea")
        config_layout = QVBoxLayout(config_area)
        config_layout.setContentsMargins(14, 14, 14, 14)
        config_layout.setSpacing(10)

        if self._subject_store is not None:
            config_layout.addWidget(self._create_subject_bar())

        # ===== 配置方式 =====
        mode_bar = QFrame()
        mode_bar.setObjectName("ModeBar")
        mode_layout = QHBoxLayout(mode_bar)
        mode_layout.setContentsMargins(12, 6, 12, 6)
        mode_layout.setSpacing(8)
        mode_label = QLabel("配置方式")
        mode_label.setStyleSheet("font-size: 11pt; font-weight: 700; color: #e7ebf2;")
        mode_layout.addWidget(mode_label)

        self._btn_mode_agent = QPushButton("智能配置")
        self._btn_mode_manual = QPushButton("手动配置")
        for button in (self._btn_mode_agent, self._btn_mode_manual):
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setMinimumHeight(34)
        self._btn_mode_agent.setChecked(True)
        self._btn_mode_agent.clicked.connect(lambda: self._set_config_mode(0))
        self._btn_mode_manual.clicked.connect(lambda: self._set_config_mode(1))
        mode_layout.addWidget(self._btn_mode_agent)
        mode_layout.addWidget(self._btn_mode_manual)
        mode_layout.addStretch()
        self._mode_status_chip = QLabel("")
        self._mode_status_chip.setStyleSheet("color: #8f9bad; font-size: 10px;")
        mode_layout.addWidget(self._mode_status_chip)
        config_layout.addWidget(mode_bar)

        # ===== 配置工作区 =====
        self._config_stack = QStackedWidget()
        self._agent_panel = AgentConfigPanel(subject_store=self._subject_store, llm_client=self._llm_client)
        self._config_stack.addWidget(self._agent_panel)

        self.param_panel = ParamPanel()
        scroll = QScrollArea()
        scroll.setObjectName("ManualConfigScroll")
        scroll.setWidget(self.param_panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._config_stack.addWidget(scroll)
        config_layout.addWidget(self._config_stack, 1)
        workspace.addWidget(config_area, 1)

        # ===== 右侧配置摘要 =====
        self._status_bar = QFrame()
        self._status_bar.setObjectName("ConfigSummaryCard")
        self._status_bar.setMinimumWidth(286)
        self._status_bar.setMaximumWidth(330)
        self._status_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        status_layout = QVBoxLayout(self._status_bar)
        status_layout.setContentsMargins(18, 18, 18, 18)
        status_layout.setSpacing(12)
        status_title = QLabel("当前配置")
        status_title.setObjectName("SummaryTitle")
        status_layout.addWidget(status_title)
        self._summary_state_label = QLabel("等待确认")
        self._summary_state_label.setObjectName("SummaryState")
        status_layout.addWidget(self._summary_state_label)
        self._summary_label = QLabel("")
        self._summary_label.setObjectName("SummaryText")
        self._summary_label.setWordWrap(True)
        self._summary_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        status_layout.addWidget(self._summary_label)
        status_layout.addSpacing(8)
        summary_hint = QLabel(
            "进入测试界面后会检查设备。设备就绪后仍需点击“开始采集”。"
        )
        summary_hint.setObjectName("SummaryHint")
        summary_hint.setWordWrap(True)
        status_layout.addWidget(summary_hint)

        # ===== 准备就绪按钮 =====
        self.btn_ready = QPushButton("进入测试准备")
        self.btn_ready.setObjectName("PrimaryStartButton")
        self.btn_ready.clicked.connect(self._on_ready_clicked)
        status_layout.addWidget(self.btn_ready)
        workspace.addWidget(self._status_bar, 0, Qt.AlignTop)
        layout.addLayout(workspace, 1)

        # ===== 连接参数变更 → 更新摘要 =====
        self._agent_panel.config_confirmed.connect(self._on_agent_config_confirmed)
        self.param_panel.config_changed.connect(self._on_param_panel_changed)
        self._update_mode_status()
        self._update_summary()

    def _create_subject_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("TopSubjectBar")

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(10)

        label = QLabel("测试对象")
        label.setMinimumWidth(64)
        label.setStyleSheet("font-size: 12px; font-weight: 700; color: #eef2f8;")

        self._subject_search = QLineEdit()
        self._subject_search.setPlaceholderText("搜索姓名")
        self._subject_search.setMinimumWidth(160)

        self._subject_combo = QComboBox()
        self._subject_combo.setMinimumWidth(260)
        self._subject_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        btn_new = MPushButton("新建")
        btn_new.setObjectName("SubjectPrimaryButton")
        btn_new.setMinimumWidth(80)

        btn_more = MPushButton("更多")
        btn_more.setMinimumWidth(80)
        menu = QMenu(btn_more)
        self._action_load_last_config = menu.addAction("加载上次参数")
        self._action_history = menu.addAction("历史记录")
        btn_more.setMenu(menu)

        layout.addWidget(label)
        layout.addWidget(self._subject_search)
        layout.addWidget(self._subject_combo, 1)
        layout.addWidget(btn_new)
        layout.addWidget(btn_more)

        self._subject_search.textChanged.connect(self._refresh_subject_results)
        self._subject_combo.currentIndexChanged.connect(self._sync_subject_to_agent)
        btn_new.clicked.connect(self._on_new_subject_clicked)
        self._action_load_last_config.triggered.connect(self._on_load_last_config_clicked)
        self._action_history.triggered.connect(self._on_history_clicked)
        self._refresh_subject_results()

        return frame

    def _refresh_subject_results(self, query: str = "") -> None:
        if self._subject_store is None or self._subject_combo is None:
            return

        current_id = self._current_subject_id()
        self._subject_combo.blockSignals(True)
        self._subject_combo.clear()
        self._subject_combo.addItem("临时测试（通用参数）", None)

        try:
            results = self._subject_store.search_subjects(query)
        except Exception:
            log.exception("Failed to search subjects")
            self._subject_combo.blockSignals(False)
            return

        selected_index = 0
        for result in results:
            self._subject_combo.addItem(self._format_subject_result(result), result)
            if result.subject.id == current_id:
                selected_index = self._subject_combo.count() - 1

        self._subject_combo.setCurrentIndex(selected_index)
        self._subject_combo.blockSignals(False)
        self._sync_subject_to_agent()

    def refresh_subjects(self) -> None:
        query = self._subject_search.text() if self._subject_search is not None else ""
        self._refresh_subject_results(query)

    def current_subject_result(self) -> SubjectSearchResult | None:
        return self._current_subject_result()

    def select_subject(self, subject_id: int) -> bool:
        if self._subject_store is None or self._subject_combo is None:
            return False
        try:
            results = self._subject_store.search_subjects("")
        except Exception:
            log.exception("Failed to select subject")
            return False
        for result in results:
            if result.subject.id != subject_id:
                continue
            if self._subject_search is not None:
                self._subject_search.setText(result.subject.display_name)
            self._add_or_select_subject(result)
            self._sync_subject_to_agent()
            return True
        return False

    def _format_subject_result(self, result: SubjectSearchResult) -> str:
        labels = result.display_labels
        parts = [result.subject.display_name]
        for key in ("Age", "Level", "Focus", "Last test"):
            value = labels.get(key)
            if value:
                parts.append(f"{key}: {value}")
        return "  |  ".join(parts)

    def _current_subject_result(self) -> SubjectSearchResult | None:
        if self._subject_combo is None:
            return None
        data = self._subject_combo.itemData(self._subject_combo.currentIndex(), Qt.UserRole)
        return data if isinstance(data, SubjectSearchResult) else None

    def _current_subject_id(self) -> int | None:
        result = self._current_subject_result()
        return result.subject.id if result else None

    def _on_new_subject_clicked(self) -> None:
        if self._subject_store is None:
            return

        dialog, name_edit, birth_year_spin, level_combo = (
            self._build_new_subject_dialog()
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        display_name = name_edit.text().strip()
        if not display_name:
            QMessageBox.warning(self, "新建受试者", "姓名不能为空。")
            return

        try:
            subject_id = self._subject_store.create_subject(
                display_name=display_name,
                birth_year=birth_year_spin.value(),
                level=level_combo.currentText(),
            )
        except Exception as exc:
            log.exception("Failed to create subject")
            QMessageBox.warning(self, "新建受试者", f"创建失败：{exc}")
            return

        try:
            created = self._find_subject_result(display_name, subject_id)
        except Exception:
            log.exception("Failed to reload created subject")
            created = None

        if self._subject_search is not None:
            self._subject_search.setText(display_name)
        if created is not None:
            self._add_or_select_subject(created)
        self._sync_subject_to_agent()

    def _build_new_subject_dialog(
        self,
    ) -> tuple[QDialog, QLineEdit, QSpinBox, QComboBox]:
        dialog = QDialog(self)
        dialog.setObjectName("NewSubjectDialog")
        dialog.setWindowTitle("新建受试者")
        dialog.setMinimumWidth(380)
        dialog.setStyleSheet(NEW_SUBJECT_DIALOG_QSS)
        form = QFormLayout(dialog)
        form.setContentsMargins(20, 20, 20, 20)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        name_edit = QLineEdit()
        birth_year_spin = QSpinBox()
        birth_year_spin.setRange(1900, datetime.now().year)
        birth_year_spin.setValue(1990)

        level_combo = QComboBox()
        level_combo.addItems(["beginner", "intermediate", "advanced"])
        level_combo.setCurrentText("intermediate")

        form.addRow("姓名", name_edit)
        form.addRow("出生年份", birth_year_spin)
        form.addRow("训练水平", level_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        return dialog, name_edit, birth_year_spin, level_combo

    def _find_subject_result(
        self, query: str, subject_id: int
    ) -> SubjectSearchResult | None:
        if self._subject_store is None:
            return None
        for result in self._subject_store.search_subjects(query):
            if result.subject.id == subject_id:
                return result
        return None

    def _add_or_select_subject(self, result: SubjectSearchResult) -> None:
        if self._subject_combo is None:
            return
        for index in range(self._subject_combo.count()):
            data = self._subject_combo.itemData(index, Qt.UserRole)
            if isinstance(data, SubjectSearchResult) and data.subject.id == result.subject.id:
                self._subject_combo.setCurrentIndex(index)
                return

        self._subject_combo.addItem(self._format_subject_result(result), result)
        self._subject_combo.setCurrentIndex(self._subject_combo.count() - 1)

    def _sync_subject_to_agent(self, *_args) -> None:
        if hasattr(self, "_agent_panel"):
            self._agent_panel.set_subject_result(self._current_subject_result())
        selected = self._current_subject_result() is not None
        if self._action_history is not None:
            self._action_history.setEnabled(selected)
        if self._action_load_last_config is not None:
            self._action_load_last_config.setEnabled(selected)

    def _on_history_clicked(self) -> None:
        result = self._current_subject_result()
        if result is None:
            QMessageBox.information(self, "历史记录", "请先选择受试者。")
            return
        self.history_requested.emit(result)

    def _on_load_last_config_clicked(self) -> None:
        if self._subject_store is None:
            return

        result = self._current_subject_result()
        if result is None:
            QMessageBox.information(self, "加载上次参数", "请先选择受试者。")
            return

        try:
            session = self._subject_store.get_last_session(result.subject.id)
        except Exception as exc:
            log.exception("Failed to load last subject session")
            QMessageBox.warning(self, "加载上次参数", f"读取失败：{exc}")
            return

        if session is None:
            QMessageBox.information(self, "加载上次参数", "该受试者暂无历史测试。")
            return

        self._set_current_config(session.config, "last_session")

    def load_config_from_history(self, config: AnyTestConfig) -> None:
        self._set_current_config(config, "history")

    def _set_config_mode(self, index: int) -> None:
        if index == self._config_mode_index:
            self._btn_mode_agent.setChecked(index == 0)
            self._btn_mode_manual.setChecked(index == 1)
            return
        self._config_mode_index = index
        self._btn_mode_agent.setChecked(index == 0)
        self._btn_mode_manual.setChecked(index == 1)
        self._update_mode_status()
        self._config_stack.setCurrentIndex(index)
        if index == 1:
            if self._current_config is not None:
                self._syncing_config_to_panel = True
                try:
                    self.param_panel.set_config(self._current_config)
                finally:
                    self._syncing_config_to_panel = False
            elif self._current_config is None:
                self.param_panel.set_test_type(self._agent_panel.current_test_type())
                self._set_current_config(self.param_panel.get_config(), "manual")

    def _update_mode_status(self) -> None:
        mode = "智能配置" if self._config_mode_index == 0 else "手动配置"
        self._mode_status_chip.setText(f"●  {mode} · 测试准备")

    def _on_agent_config_confirmed(self, config: AnyTestConfig) -> None:
        self._set_current_config(config, "agent")

    def _on_param_panel_changed(self) -> None:
        if self._syncing_config_to_panel:
            return
        if self._config_mode_index == 1:
            self._set_current_config(self.param_panel.get_config(), "manual")

    def _set_current_config(self, config: AnyTestConfig, source: str) -> None:
        self._current_config = config
        self._config_source = source
        self._config_errors = validate_runtime_config(config)
        if source in {"last_session", "history"}:
            self._syncing_config_to_panel = True
            try:
                self.param_panel.set_config(config)
            finally:
                self._syncing_config_to_panel = False
        self._update_summary()

    def _update_summary(self):
        """根据已确认配置更新配置摘要。"""
        config = self._current_config
        if config is None:
            self._summary_label.setText("未确认，请生成建议配置或切换到手动配置。")
            self._summary_state_label.setText("等待确认")
            self._sync_summary_label_height()
            if hasattr(self, "btn_ready"):
                self.btn_ready.setEnabled(False)
            return

        source_labels = {
            "agent": "智能配置",
            "manual": "手动配置",
            "last_session": "上次参数",
            "history": "历史参数",
        }
        source = source_labels.get(self._config_source or "", "当前配置")
        mode = getattr(config, "mode_label", config.test_type)
        parts = [f"{source} · {mode}"]
        if hasattr(config, "start_type"):
            parts.append(f"启动：{config.start_type}")
        parts.append(f"停止：{config.stop_type}")
        if getattr(config, "number_of_jumps", None):
            parts.append(f"目标：{config.number_of_jumps} 次")
        if getattr(config, "test_length", None):
            parts.append(f"时长：{config.test_length}")
        if hasattr(config, "treadmill_speed"):
            parts.append(f"速度：{config.treadmill_speed:g} km/h")
        if hasattr(config, "direction"):
            parts.append(f"方向：{config.direction}")
        parts.append(
            f"阈值：接触 >{config.min_contact_time} ms / "
            f"腾空 >{config.min_flight_time} ms"
        )
        if getattr(config, "metronome_enabled", False):
            parts.append(f"节拍器：{config.metronome_bpm} BPM")

        self._summary_label.setText("\n".join(parts))
        if self._config_errors:
            self._summary_state_label.setText("配置需要修正")
            self._summary_label.setText(
                self._summary_label.text()
                + "\n\n"
                + "\n".join(f"• {error}" for error in self._config_errors)
            )
        else:
            self._summary_state_label.setText("配置已确认")
        self._sync_summary_label_height()
        if hasattr(self, "btn_ready"):
            self.btn_ready.setEnabled(not self._config_errors)

    def _sync_summary_label_height(self) -> None:
        self._summary_label.ensurePolished()
        content_width = max(220, self._status_bar.minimumWidth() - 36)
        content_height = self._summary_label.heightForWidth(content_width)
        minimum_height = max(
            content_height,
            self._summary_label.fontMetrics().lineSpacing() * 2,
        )
        self._summary_label.setMinimumHeight(minimum_height)
        self._summary_label.updateGeometry()
        self._status_bar.updateGeometry()

    def _on_ready_clicked(self):
        """收集配置并发射信号。"""
        if self._current_config is None:
            QMessageBox.information(self, "准备就绪", "请先确认一份测试配置。")
            return
        self._config_errors = validate_runtime_config(self._current_config)
        if self._config_errors:
            QMessageBox.warning(
                self,
                "配置需要修正",
                "\n".join(self._config_errors),
            )
            self._update_summary()
            return
        config = self._current_config
        result = self._current_subject_result()
        snapshot = self._agent_panel.current_profile_snapshot()
        snapshot["display_name"] = (
            result.subject.display_name if result else "临时测试"
        )
        self.ready_signal.emit(
            SessionSetup(
                config=config,
                subject_id=result.subject.id if result else None,
                subject=result.subject if result else None,
                subject_snapshot=snapshot,
                config_source=self._config_source,
            )
        )
