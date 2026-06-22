"""
history_view.py — 受试者历史记录页

显示当前受试者的历史测试列表和摘要，并允许加载某次测试参数。
"""

from __future__ import annotations

import logging
from typing import Any

from qtpy.QtCore import Signal, Qt
from qtpy.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QHBoxLayout, QLabel,
    QMessageBox, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from dayu_widgets.divider import MDivider
from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton

from data.subject_store import SessionRecord, SubjectSearchResult, SubjectStore


log = logging.getLogger(__name__)


class HistoryView(QWidget):
    """只读历史记录视图。"""

    return_setup = Signal()
    load_config_requested = Signal(object)

    def __init__(self, subject_store: SubjectStore | None = None, parent=None):
        super().__init__(parent)
        self._subject_store = subject_store
        self._subject_result: SubjectSearchResult | None = None
        self._sessions: list[SessionRecord] = []
        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 15, 20, 15)
        main_layout.setSpacing(12)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        title = MLabel("历史记录")
        title.setStyleSheet(
            "font-size: 22pt; font-weight: bold; color: #e0e0e0;"
        )
        self._subject_label = MLabel("未选择受试者")
        self._subject_label.setStyleSheet("font-size: 11pt; color: #c8c8c8;")

        self._btn_return = MPushButton("返回配置页")
        self._btn_return.clicked.connect(self.return_setup)

        header_layout.addWidget(title)
        header_layout.addWidget(self._subject_label, 1)
        header_layout.addWidget(self._btn_return)
        main_layout.addLayout(header_layout)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)

        self._session_table = QTableWidget(0, 4)
        self._session_table.setHorizontalHeaderLabels(
            ["时间", "测试类型", "结束原因", "结果摘要"]
        )
        self._session_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._session_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._session_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._session_table.verticalHeader().setVisible(False)
        self._session_table.horizontalHeader().setStretchLastSection(True)
        self._session_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self._session_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self._session_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self._session_table.itemSelectionChanged.connect(self._on_selection_changed)
        content_layout.addWidget(self._session_table, 5)

        detail_frame = QFrame()
        detail_frame.setStyleSheet(
            "QFrame { "
            "  background-color: rgba(35, 35, 40, 0.65); "
            "  border-radius: 6px; "
            "}"
        )
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(14, 12, 14, 12)
        detail_layout.setSpacing(8)
        detail_layout.addWidget(MDivider("记录摘要"))

        self._detail_label = QLabel("请选择一条历史记录。")
        self._detail_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._detail_label.setWordWrap(True)
        self._detail_label.setStyleSheet(
            "font-size: 11pt; color: #e0e0e0; line-height: 150%;"
        )
        self._detail_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        detail_layout.addWidget(self._detail_label, 1)

        content_layout.addWidget(detail_frame, 4)
        main_layout.addLayout(content_layout, 1)

        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        self._btn_load_config = MPushButton("加载该次参数").primary()
        self._btn_load_config.setMinimumHeight(42)
        self._btn_load_config.setMinimumWidth(160)
        self._btn_load_config.clicked.connect(self._on_load_config_clicked)
        footer_layout.addWidget(self._btn_load_config)
        main_layout.addLayout(footer_layout)

        self._set_empty_state("请从配置页选择受试者后查看历史记录。")

    def load_subject(self, result: SubjectSearchResult | None) -> None:
        self._subject_result = result
        if result is None:
            self._subject_label.setText("未选择受试者")
            self._set_empty_state("请先选择受试者。")
            return
        if self._subject_store is None:
            self._subject_label.setText(f"受试者: {result.subject.display_name}")
            self._set_empty_state("历史数据存储不可用。")
            return

        self._subject_label.setText(f"受试者: {result.subject.display_name}")
        try:
            self._sessions = self._subject_store.get_sessions(result.subject.id)
        except Exception as exc:
            log.exception("Failed to load subject sessions")
            self._set_empty_state("读取历史记录失败。")
            QMessageBox.warning(self, "历史记录", f"读取失败：{exc}")
            return

        self._populate_sessions()

    def _populate_sessions(self) -> None:
        self._session_table.blockSignals(True)
        self._session_table.setRowCount(0)
        for row, session in enumerate(self._sessions):
            self._session_table.insertRow(row)
            values = [
                session.started_at[:16],
                session.test_type,
                _finish_reason_label(session.finish_reason),
                _session_summary(session),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, session)
                self._session_table.setItem(row, column, item)
        self._session_table.blockSignals(False)

        if self._sessions:
            self._session_table.selectRow(0)
            self._show_session_detail(self._sessions[0])
            self._btn_load_config.setEnabled(True)
        else:
            self._set_empty_state("该受试者暂无历史测试。")

    def _set_empty_state(self, message: str) -> None:
        self._sessions = []
        self._session_table.setRowCount(0)
        self._detail_label.setText(message)
        self._btn_load_config.setEnabled(False)

    def _on_selection_changed(self) -> None:
        session = self._selected_session()
        if session is None:
            self._detail_label.setText("请选择一条历史记录。")
            self._btn_load_config.setEnabled(False)
            return
        self._show_session_detail(session)
        self._btn_load_config.setEnabled(True)

    def _selected_session(self) -> SessionRecord | None:
        row = self._session_table.currentRow()
        if row < 0:
            return None
        item = self._session_table.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.UserRole)
        return data if isinstance(data, SessionRecord) else None

    def _show_session_detail(self, session: SessionRecord) -> None:
        config = session.config
        summary = session.report_summary
        lines = [
            f"测试时间: {session.started_at[:16]}",
            f"测试类型: {session.test_type}",
            f"结束原因: {_finish_reason_label(session.finish_reason)}",
            "",
            "参数摘要:",
            f"启动: {config.start_type} / {config.start_position}",
            f"停止: {config.stop_type} / {config.finish_position or '-'}",
            f"目标跳跃: {config.number_of_jumps or '-'} 次",
            f"接触/腾空阈值: >{config.min_contact_time}ms / >{config.min_flight_time}ms",
            "",
            "结果摘要:",
            _session_summary(session),
        ]
        if session.total_jumps is not None:
            lines.append(f"总跳跃: {session.total_jumps} 次")
        if summary.get("touch_count") is not None:
            lines.append(f"触地次数: {summary['touch_count']}")
        if summary.get("lift_count") is not None:
            lines.append(f"腾空次数: {summary['lift_count']}")
        if summary.get("std_jump_height") is not None:
            lines.append(f"跳高标准差: {summary['std_jump_height']:.3f} m")
        if summary.get("min_air_time") is not None and summary.get("max_air_time") is not None:
            lines.append(
                f"腾空范围: {summary['min_air_time']:.3f} - {summary['max_air_time']:.3f} s"
            )
        if (
            summary.get("min_contact_time") is not None
            and summary.get("max_contact_time") is not None
        ):
            lines.append(
                f"触地范围: {summary['min_contact_time']:.3f} - "
                f"{summary['max_contact_time']:.3f} s"
            )
        self._detail_label.setText("\n".join(lines))

    def _on_load_config_clicked(self) -> None:
        session = self._selected_session()
        if session is None:
            QMessageBox.information(self, "加载该次参数", "请先选择一条历史记录。")
            return
        self.load_config_requested.emit(session.config)


def _finish_reason_label(reason: str | None) -> str:
    labels = {
        "jump_count_reached": "跳跃次数已达标",
        "time_up": "测试时间到",
        "manual": "手动结束",
        "error": "异常结束",
    }
    if not reason:
        return "-"
    return labels.get(reason, reason)


def _session_summary(session: SessionRecord) -> str:
    summary: dict[str, Any] = session.report_summary
    report_type = summary.get("report_type")
    if report_type == "jump":
        max_height = summary.get("max_jump_height")
        avg_height = summary.get("avg_jump_height")
        if max_height is not None and avg_height is not None:
            return f"最大跳高 {max_height:.3f}m / 平均 {avg_height:.3f}m"
        if session.total_jumps is not None:
            return f"跳跃 {session.total_jumps} 次"
    if report_type == "gait":
        avg_stride = summary.get("avg_stride")
        avg_velocity = summary.get("avg_velocity")
        if avg_stride is not None and avg_velocity is not None:
            return f"平均步长 {avg_stride:.3f}m / 平均步速 {avg_velocity:.3f}m/s"
    if session.total_jumps is not None:
        return f"跳跃 {session.total_jumps} 次"
    return "-"
