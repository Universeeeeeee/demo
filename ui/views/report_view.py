"""
report_view.py — 测试报告页

接收 TestReport (不可变 dataclass) 展示统计汇总和图表回顾。
不依赖 GaitEngine，所有数据来自 TestReport。

功能:
  - MetricCard 网格展示核心统计指标
  - pyqtgraph 图表展示全量历史数据（非滑动窗口）
  - Excel 导出按钮
  - 返回首页按钮
"""

from __future__ import annotations

import importlib
import math
import os
import time
from typing import Optional

from openpyxl import Workbook

from qtpy.QtCore import Signal, Qt
from qtpy.QtGui import QColor, QPainter
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QSizePolicy, QMessageBox, QFileDialog,
    QScrollArea, QTabWidget,
)

from dayu_widgets.label import MLabel
from dayu_widgets.divider import MDivider
from dayu_widgets.push_button import MPushButton
from dayu_widgets import dayu_theme

from config.test_report import TestReport, JumpTestReport, GaitTestReport
from config.treadmill_report import (
    TreadmillGaitReport,
    TreadmillRunningReport,
    GaitCycleRecord,
    TreadmillStepResult,
)
from path_utils import get_base_dir as _get_base_dir
from ui.footprint_channel import FootprintReplayPanel

# pyqtgraph 可选
try:
    _pg_spec = importlib.util.find_spec("pyqtgraph")
    if _pg_spec is not None:
        pg = importlib.import_module("pyqtgraph")
        _PG_AVAILABLE = True
    else:
        pg = None
        _PG_AVAILABLE = False
except Exception:
    pg = None
    _PG_AVAILABLE = False

G = 9.81

REPORT_QSS = """
QWidget#ReportViewRoot {
    background-color: #0c1119;
    color: #e7ebf2;
}
QTabWidget#ReportTabs::pane {
    border: 1px solid #354151;
    border-radius: 6px;
    background-color: #0c1119;
}
QTabWidget#ReportTabs QTabBar::tab {
    min-width: 96px;
    min-height: 30px;
    padding: 4px 16px;
    border: 1px solid #354151;
    border-bottom: none;
    background-color: #171f2b;
    color: #aeb7c5;
}
QTabWidget#ReportTabs QTabBar::tab:selected {
    background-color: #222d3c;
    color: #ff8a1f;
    font-weight: 650;
}
QTabWidget#ReportTabs QTabBar::tab:hover {
    background-color: #1d2735;
    color: #f4f6f9;
}
QScrollArea#StatsScroll,
QScrollArea#StatsScroll QWidget#qt_scrollarea_viewport,
QWidget#StatsContent {
    background: transparent;
    border: none;
}
QScrollArea#StatsScroll QScrollBar:vertical {
    width: 10px;
    margin: 0;
    border: none;
    background-color: #0f1620;
}
QScrollArea#StatsScroll QScrollBar::handle:vertical {
    min-height: 32px;
    border-radius: 5px;
    background-color: #3a4656;
}
QScrollArea#StatsScroll QScrollBar::handle:vertical:hover {
    background-color: #4b596b;
}
QScrollArea#StatsScroll QScrollBar::add-line:vertical,
QScrollArea#StatsScroll QScrollBar::sub-line:vertical {
    height: 0;
    background: transparent;
}
QScrollArea#StatsScroll QScrollBar::add-page:vertical,
QScrollArea#StatsScroll QScrollBar::sub-page:vertical {
    background: transparent;
}
QPushButton#ReportSecondaryButton,
QPushButton#ReportPrimaryButton {
    min-height: 45px;
    min-width: 160px;
    border-radius: 8px;
    font-size: 14pt;
}
QPushButton#ReportSecondaryButton {
    background-color: #1a2230;
    border: 1px solid #354151;
    color: #d9dee8;
}
QPushButton#ReportSecondaryButton:hover {
    background-color: #232d3c;
}
QPushButton#ReportPrimaryButton {
    background-color: #ff7a00;
    border: 1px solid #ff7a00;
    color: white;
    font-weight: 700;
}
QPushButton#ReportPrimaryButton:hover {
    background-color: #ff8a1f;
}
"""


# ======================================================================
#  StatCard — 报告页统计卡片 (比 ExecutionView 的 MetricCard 更紧凑)
# ======================================================================

class StatCard(QFrame):
    """统计指标卡片: 标签 + 数值，适合网格排列。"""

    def __init__(self, label: str, value: str = "--", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "StatCard {"
            "  background-color: rgba(40, 40, 45, 0.85);"
            "  border: 1px solid rgba(80, 80, 85, 0.5);"
            "  border-radius: 8px;"
            "  padding: 6px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignCenter)

        self._label = MLabel(label)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            "font-size: 10pt; color: #888888; border: none; background: transparent;"
        )
        layout.addWidget(self._label)

        self._value = MLabel(value)
        self._value.setAlignment(Qt.AlignCenter)
        self._value.setStyleSheet(
            "font-size: 26pt; font-weight: bold; "
            "color: #f0f0f0; border: none; background: transparent;"
        )
        layout.addWidget(self._value)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(85)

    def set_value(self, text: str):
        self._value.setText(text)
        self._apply_value_style("#f0f0f0")

    def set_color(self, color: str):
        self._apply_value_style(color)

    def _apply_value_style(self, color: str):
        text = self._value.text()
        font_size = 18 if len(text) >= 11 else 26
        self._value.setStyleSheet(
            f"font-size: {font_size}pt; font-weight: bold; "
            f"color: {color}; border: none; background: transparent;"
        )


class CyclePhaseBar(QWidget):
    """Compact horizontal rendering of one completed gait cycle."""

    _COLORS = {
        "负荷反应期": QColor("#8e44ad"),
        "单支撑": QColor("#16a085"),
        "摆动前期": QColor("#c0392b"),
        "支撑相": QColor("#2980b9"),
        "摆动相": QColor("#f39c12"),
    }

    def __init__(self, cycle: GaitCycleRecord, parent=None):
        super().__init__(parent)
        self._cycle = cycle
        self.setMinimumHeight(24)
        if self._detailed_stance_is_complete():
            tooltip = "负荷反应期、单支撑、摆动前期和摆动相按实际时长绘制"
        else:
            tooltip = "子阶段无法可靠拆分，按支撑相和摆动相绘制"
        self.setToolTip(tooltip)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        total = self._cycle.gait_cycle_s
        if total <= 0:
            return
        segments = self._segments()
        x = 0.0
        for label, duration in segments:
            if duration is None or duration <= 0:
                continue
            width = self.width() * duration / total
            painter.fillRect(int(x), 2, max(int(width), 1), self.height() - 4, self._COLORS[label])
            x += width

    def _segments(self):
        if self._detailed_stance_is_complete():
            return [
                ("负荷反应期", self._cycle.load_response_s),
                ("单支撑", self._cycle.single_support_s),
                ("摆动前期", self._cycle.pre_swing_s),
                ("摆动相", self._cycle.swing_phase_s),
            ]
        return [
            ("支撑相", self._cycle.stance_phase_s),
            ("摆动相", self._cycle.swing_phase_s),
        ]

    def _detailed_stance_is_complete(self) -> bool:
        detailed = (
            self._cycle.load_response_s,
            self._cycle.single_support_s,
            self._cycle.pre_swing_s,
        )
        if (
            self._cycle.stance_phase_s is None
            or any(value is None or value < 0 for value in detailed)
        ):
            return False
        return math.isclose(
            sum(detailed),
            self._cycle.stance_phase_s,
            rel_tol=1e-6,
            abs_tol=1e-9,
        )


# ======================================================================
#  ReportView
# ======================================================================

class ReportView(QWidget):
    """测试报告视图 — 统计汇总 + 图表回顾 + 导出。"""

    return_home = Signal()
    export_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._report: Optional[TestReport] = None
        self._dynamic_widgets: list[QWidget] = []
        self._build_ui()

    def _build_ui(self):
        self.setObjectName("ReportViewRoot")
        self.setStyleSheet(REPORT_QSS)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 15, 20, 15)
        main_layout.setSpacing(12)

        # ===== 标题 =====
        self._title = MLabel("📊 测试报告")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(
            "font-size: 22pt; font-weight: bold; color: #e0e0e0; padding: 6px 0;"
        )
        main_layout.addWidget(self._title)

        # ===== 结束原因 =====
        self._reason_label = MLabel("")
        self._reason_label.setAlignment(Qt.AlignCenter)
        self._reason_label.setStyleSheet(
            "font-size: 12pt; color: #52c41a; padding: 2px 0;"
        )
        main_layout.addWidget(self._reason_label)

        # ===== 内容区: 概览页 + 明细页 =====
        self._tabs = QTabWidget()
        self._tabs.setObjectName("ReportTabs")
        self._tabs.setDocumentMode(True)

        self._overview_page = QWidget()
        content_layout = QHBoxLayout(self._overview_page)
        content_layout.setContentsMargins(4, 8, 4, 4)
        content_layout.setSpacing(16)

        # --- 左侧: 统计卡片网格 ---
        left_container = QWidget()
        left_container.setObjectName("StatsContent")
        left_container.setMinimumWidth(380)
        left_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._stats_content = left_container
        self._stats_layout = QGridLayout(left_container)
        self._stats_layout.setContentsMargins(0, 0, 0, 0)
        self._stats_layout.setSpacing(8)

        # 预创建统计卡片槽位，纵跳报告会展示更多统计项。
        self._stat_cards: list[StatCard] = []
        for i in range(16):
            card = StatCard("")
            card.hide()
            row, col = divmod(i, 2)
            self._stats_layout.addWidget(card, row, col)
            self._stat_cards.append(card)

        self._stats_scroll = QScrollArea()
        self._stats_scroll.setObjectName("StatsScroll")
        self._stats_scroll.setWidgetResizable(True)
        self._stats_scroll.setFrameShape(QFrame.NoFrame)
        self._stats_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._stats_scroll.setMinimumWidth(400)
        self._stats_scroll.setMaximumWidth(560)
        self._stats_scroll.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Expanding
        )
        self._stats_scroll.setWidget(left_container)
        content_layout.addWidget(self._stats_scroll, 0)
        content_layout.addStretch(1)

        # --- 右侧: 图表回顾 ---
        right_container = QWidget()
        right_container.setMinimumWidth(460)
        right_container.setMaximumWidth(780)
        right_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        self._right_layout = right_layout

        right_layout.addWidget(MDivider("数据回顾"))

        self._replay_panel = FootprintReplayPanel()
        self._replay_panel.hide()
        self._replay_panel.setMinimumHeight(520)
        right_layout.addWidget(self._replay_panel, 1)

        self._plot_container = QWidget()
        self._plot_container_layout = QVBoxLayout(self._plot_container)
        self._plot_container_layout.setContentsMargins(0, 0, 0, 0)
        self._plot_container_layout.setSpacing(8)

        if _PG_AVAILABLE:
            self._plot_1 = pg.PlotWidget()
            self._plot_1.setBackground(dayu_theme.background_in_color)
            self._plot_1.showGrid(x=True, y=True, alpha=0.1)
            self._plot_1.enableAutoRange()
            self._plot_container_layout.addWidget(self._plot_1, 1)

            self._plot_2 = pg.PlotWidget()
            self._plot_2.setBackground(dayu_theme.background_in_color)
            self._plot_2.showGrid(x=True, y=True, alpha=0.1)
            self._plot_2.enableAutoRange()
            self._plot_container_layout.addWidget(self._plot_2, 1)
        else:
            placeholder = QLabel("未安装 pyqtgraph — 图表不可用")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("font-size: 14pt; color: #666;")
            self._plot_container_layout.addWidget(placeholder)

        right_layout.addWidget(self._plot_container, 1)

        content_layout.addWidget(right_container, 0)
        self._tabs.addTab(self._overview_page, "概览")

        self._details_page = QScrollArea()
        self._details_page.setWidgetResizable(True)
        self._details_page.setFrameShape(QFrame.NoFrame)
        self._details_content = QWidget()
        self._details_layout = QVBoxLayout(self._details_content)
        self._details_layout.setContentsMargins(8, 8, 8, 8)
        self._details_layout.setSpacing(12)
        self._details_layout.setAlignment(Qt.AlignTop)
        self._details_page.setWidget(self._details_content)
        self._tabs.addTab(self._details_page, "明细")

        main_layout.addWidget(self._tabs, 1)

        # ===== 底部按钮 =====
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        btn_layout.addStretch()

        self.btn_export = MPushButton("📥 导出 Excel")
        self.btn_export.setObjectName("ReportSecondaryButton")
        self.btn_export.setMinimumHeight(45)
        self.btn_export.setMinimumWidth(160)
        self.btn_export.clicked.connect(self._on_export)
        btn_layout.addWidget(self.btn_export)

        self.btn_home = MPushButton("返回测试").primary()
        self.btn_home.setObjectName("ReportPrimaryButton")
        self.btn_home.setMinimumHeight(45)
        self.btn_home.setMinimumWidth(160)
        self.btn_home.clicked.connect(self.return_home)
        btn_layout.addWidget(self.btn_home)

        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    #  公共接口
    # ------------------------------------------------------------------

    def load_report(self, report: TestReport):
        """填充统计卡片和图表。"""
        self._report = report

        # 结束原因
        reason_map = {
            "jump_count_reached": "✅ 跳跃次数已达标",
            "time_up": "✅ 测试时间到",
            "manual": "⏹ 手动结束",
        }
        self._reason_label.setText(reason_map.get(report.finish_reason, report.finish_reason))
        self._replay_panel.hide()
        self._plot_container.show()
        self._tabs.setCurrentIndex(0)
        self._clear_dynamic_widgets()

        if isinstance(report, JumpTestReport):
            self._load_jump_report(report)
        elif isinstance(report, GaitTestReport):
            self._load_gait_report(report)
        elif isinstance(report, (TreadmillGaitReport, TreadmillRunningReport)):
            self._load_treadmill_report(report)

    # ------------------------------------------------------------------
    #  纵跳报告
    # ------------------------------------------------------------------

    def _load_jump_report(self, r: JumpTestReport):
        self._title.setText("📊 测试报告 — 纵跳测试")

        # 统计卡片
        stats = [
            ("触地次数", f"{r.touch_count}"),
            ("腾空次数", f"{r.lift_count}"),
            ("最大跳高", f"{r.max_jump_height:.3f} m"),
            ("平均跳高", f"{r.avg_jump_height:.3f} m"),
            ("最小跳高", f"{r.min_jump_height:.3f} m"),
            ("跳高标准差", f"{r.std_jump_height:.3f} m"),
            ("最大腾空", f"{r.max_air_time:.3f} s"),
            ("平均腾空", f"{r.avg_air_time:.3f} s"),
            ("最小腾空", f"{r.min_air_time:.3f} s"),
            ("腾空标准差", f"{r.std_air_time:.3f} s"),
            ("最大触地", f"{r.max_contact_time:.3f} s"),
            ("平均触地", f"{r.avg_contact_time:.3f} s"),
            ("最小触地", f"{r.min_contact_time:.3f} s"),
            ("触地标准差", f"{r.std_contact_time:.3f} s"),
            ("平均跳跃节奏", f"{r.avg_cadence:.1f} jumps/min" if r.avg_cadence else "--"),
        ]
        self._fill_stat_cards(stats)

        # 高亮最大跳高
        if len(self._stat_cards) > 2:
            self._stat_cards[2].set_color(dayu_theme.primary_color)

        # 图表: 全量数据
        if _PG_AVAILABLE and r.jump_heights:
            heights = list(r.jump_heights)
            x = list(range(1, len(heights) + 1))

            self._plot_1.clear()
            self._plot_1.setLabel('left', '跳高 (m)')
            self._plot_1.setLabel('bottom', '跳跃次数')
            bar1 = pg.BarGraphItem(x=x, height=heights, width=0.65, brush=dayu_theme.primary_color)
            self._plot_1.addItem(bar1)

            self._plot_2.clear()
            self._plot_2.setLabel('left', '腾空时间 (s)')
            self._plot_2.setLabel('bottom', '跳跃次数')
            bar2 = pg.BarGraphItem(x=x, height=list(r.air_times), width=0.65, brush='#52c41a')
            self._plot_2.addItem(bar2)

    # ------------------------------------------------------------------
    #  步态报告
    # ------------------------------------------------------------------

    def _load_gait_report(self, r: GaitTestReport):
        self._title.setText("📊 测试报告 — 步态分析")
        self._plot_container.hide()
        self._replay_panel.show()
        self._replay_panel.set_direction("Interface side")
        self._replay_panel.set_timeline(getattr(r, "visual_timeline", ()))

        stats = [
            ("总步数", f"{r.touch_count}"),
            ("离地次数", f"{r.lift_count}"),
            ("平均步长", f"{r.avg_stride:.2f} cm"),
            ("最大步长", f"{r.max_stride:.2f} cm"),
            ("平均步速", f"{r.avg_velocity:.2f} cm/s"),
            ("最大步速", f"{r.max_velocity:.2f} cm/s"),
        ]

        if r.imbalance_index is not None:
            stats.append(("不平衡指数", f"{r.imbalance_index:.1f}%"))
        if r.avg_double_support is not None:
            stats.append(("双支撑期", f"{r.avg_double_support:.3f} s"))

        self._fill_stat_cards(stats)

        # 图表
        if _PG_AVAILABLE and r.stride_lengths:
            x = list(range(1, len(r.stride_lengths) + 1))

            self._plot_1.clear()
            self._plot_1.setLabel('left', '步长 (cm)')
            self._plot_1.setLabel('bottom', '步数')
            bar1 = pg.BarGraphItem(x=x, height=list(r.stride_lengths), width=0.65, brush=dayu_theme.primary_color)
            self._plot_1.addItem(bar1)

        if _PG_AVAILABLE and r.velocities:
            x2 = list(range(1, len(r.velocities) + 1))
            self._plot_2.clear()
            self._plot_2.setLabel('left', '步速 (cm/s)')
            self._plot_2.setLabel('bottom', '步数')
            bar2 = pg.BarGraphItem(x=x2, height=list(r.velocities), width=0.65, brush='#52c41a')
            self._plot_2.addItem(bar2)

    # ------------------------------------------------------------------
    #  跑步机报告
    # ------------------------------------------------------------------

    def _load_treadmill_report(self, r: TreadmillGaitReport | TreadmillRunningReport):
        test_type_label = "跑步机步态" if isinstance(r, TreadmillGaitReport) else "跑步机跑步"
        self._title.setText(f"测试报告 — {test_type_label}")
        self._plot_container.hide()
        self._replay_panel.show()

        # 配置快照
        snap = r.report_config_snapshot
        speed = snap.get("treadmill_speed", "--")
        direction = snap.get("direction", "--")
        self._replay_panel.set_direction(direction)
        self._replay_panel.set_timeline(getattr(r, "visual_timeline", ()))
        foot_length = r.foot_length_cm_snapshot

        # 总览指标
        stats = [
            ("触地次数", f"{r.touch_count}"),
            ("离地次数", f"{r.lift_count}"),
            ("有效步数", f"{sum(1 for s in r.per_step_results if s.is_included_in_statistics)}"),
            ("起始脚", _side_label(r.resolved_starting_foot)),
            ("速度", f"{speed} km/h"),
            ("方向", direction),
            ("足长", f"{foot_length} cm" if foot_length else "--"),
        ]
        left_count = sum(
            1 for cycle in r.gait_cycles
            if cycle.side == "left" and cycle.is_included_in_statistics
        )
        right_count = sum(
            1 for cycle in r.gait_cycles
            if cycle.side == "right" and cycle.is_included_in_statistics
        )
        stats.extend([
            ("左脚有效周期", str(left_count)),
            ("右脚有效周期", str(right_count)),
        ])
        if r.gait_cycles:
            cycle_summary = r.cycle_metric_summaries.get("gait_cycle_s")
            stance_summary = r.cycle_metric_summaries.get("stance_phase_percent")
            swing_summary = r.cycle_metric_summaries.get("swing_phase_percent")
            if cycle_summary and cycle_summary.mean is not None:
                stats.append(("平均步态周期", f"{cycle_summary.mean:.3f} s"))
            if stance_summary and stance_summary.mean is not None:
                stats.append(("平均支撑相", f"{stance_summary.mean:.1f}%"))
            if swing_summary and swing_summary.mean is not None:
                stats.append(("平均摆动相", f"{swing_summary.mean:.1f}%"))
        self._fill_stat_cards(stats)

        if r.gait_cycles:
            self._build_cycle_timeline(r.gait_cycles)
            self._build_cycle_detail_table(r.gait_cycles)
            self._build_cycle_summary_table(r)

        # 逐步详情表
        if r.per_step_results:
            self._build_treadmill_step_table(r.per_step_results)

        # 指标汇总
        if r.metric_summaries:
            self._build_treadmill_metric_summary(r.metric_summaries)

        # 左右侧对比
        if r.left_right_results:
            self._build_treadmill_left_right(r.left_right_results)

    def _build_cycle_timeline(self, cycles: tuple[GaitCycleRecord, ...]):
        from qtpy.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

        table = QTableWidget(len(cycles), 6)
        table.setHorizontalHeaderLabels([
            "序号", "脚", "周期阶段图", "周期 (s)", "纳入统计", "统计说明",
        ])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for row, cycle in enumerate(cycles):
            side = "左脚" if cycle.side == "left" else "右脚" if cycle.side == "right" else "未知脚"
            for column, text in enumerate((str(cycle.index + 1), side)):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, column, item)
            table.setCellWidget(row, 2, CyclePhaseBar(cycle))
            item = QTableWidgetItem(_fmt(cycle.gait_cycle_s))
            item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 3, item)
            included_item = QTableWidgetItem(
                "是" if cycle.is_included_in_statistics else "否"
            )
            included_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 4, included_item)
            note_item = QTableWidgetItem(
                _statistics_note(
                    cycle.is_included_in_statistics,
                    cycle.statistics_exclusion_reason,
                    cycle.quality_flags,
                )
            )
            note_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 5, note_item)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        table.setMinimumHeight(min(max(len(cycles) * 30 + 52, 120), 420))
        self._cycle_timeline_table = table
        self._add_detail_widget(table)

    def _build_cycle_detail_table(self, cycles: tuple[GaitCycleRecord, ...]):
        from qtpy.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

        columns = [
            "序号", "脚", "步态周期(s)", "支撑相(s)", "支撑相(%)",
            "摆动相(s)", "摆动相(%)", "步时间(s)", "单支撑(s)",
            "单支撑(%)", "总双支撑(s)", "总双支撑(%)",
            "负荷反应期(s)", "负荷反应期(%)", "摆动前期(s)",
            "摆动前期(%)", "腾空时间(s)", "纳入统计", "统计说明",
        ]
        table = QTableWidget(len(cycles), len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setAlternatingRowColors(True)
        for row, cycle in enumerate(cycles):
            values = [
                str(cycle.index + 1),
                "左脚" if cycle.side == "left" else "右脚" if cycle.side == "right" else "未知脚",
                _fmt(cycle.gait_cycle_s),
                _fmt(cycle.stance_phase_s),
                _fmt(cycle.stance_phase_percent),
                _fmt(cycle.swing_phase_s),
                _fmt(cycle.swing_phase_percent),
                _fmt(cycle.step_time_s),
                _fmt(cycle.single_support_s),
                _fmt(cycle.single_support_percent),
                _fmt(cycle.total_double_support_s),
                _fmt(cycle.total_double_support_percent),
                _fmt(cycle.load_response_s),
                _fmt(cycle.load_response_percent),
                _fmt(cycle.pre_swing_s),
                _fmt(cycle.pre_swing_percent),
                _fmt(cycle.total_flight_time_s),
                "是" if cycle.is_included_in_statistics else "否",
                _statistics_note(
                    cycle.is_included_in_statistics,
                    cycle.statistics_exclusion_reason,
                    cycle.quality_flags,
                ),
            ]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text or "N/A")
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, column, item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.setMinimumHeight(min(max(len(cycles) * 28 + 52, 120), 520))
        self._cycle_detail_table = table
        self._add_detail_widget(table)

    def _build_cycle_summary_table(
        self, report: TreadmillGaitReport | TreadmillRunningReport
    ):
        from qtpy.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

        names = {
            "gait_cycle_s": "步态周期 (s)",
            "stance_phase_s": "支撑相 (s)",
            "stance_phase_percent": "支撑相 (%)",
            "swing_phase_s": "摆动相 (s)",
            "swing_phase_percent": "摆动相 (%)",
            "step_time_s": "步时间 (s)",
            "single_support_s": "单支撑 (s)",
            "single_support_percent": "单支撑 (%)",
            "total_double_support_s": "总双支撑 (s)",
            "total_double_support_percent": "总双支撑 (%)",
            "load_response_s": "负荷反应期 (s)",
            "load_response_percent": "负荷反应期 (%)",
            "pre_swing_s": "摆动前期 (s)",
            "pre_swing_percent": "摆动前期 (%)",
            "total_flight_time_s": "腾空时间 (s)",
        }
        rows = []
        for key, summary in report.cycle_metric_summaries.items():
            if summary.count == 0:
                continue
            left = report.cycle_side_summaries.get("left", {}).get(key)
            right = report.cycle_side_summaries.get("right", {}).get(key)
            rows.append([
                names.get(key, key),
                _fmt(summary.mean),
                str(left.count if left else 0),
                _fmt(left.mean if left else None),
                str(right.count if right else 0),
                _fmt(right.mean if right else None),
                _fmt(report.cycle_asymmetry_percent.get(key)),
            ])

        table = QTableWidget(len(rows), 7)
        table.setHorizontalHeaderLabels([
            "指标", "总体均值", "左脚数量", "左脚均值",
            "右脚数量", "右脚均值", "不对称率(%)",
        ])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setAlternatingRowColors(True)
        for row_index, row in enumerate(rows):
            for column, text in enumerate(row):
                item = QTableWidgetItem(text or "N/A")
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, column, item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.setMinimumHeight(max(len(rows) * 28 + 52, 120))
        self._cycle_summary_table = table
        self._add_detail_widget(table)

    def _build_treadmill_step_table(self, steps: tuple[TreadmillStepResult, ...]):
        """Build step detail table below the stat cards."""
        from qtpy.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

        columns = [
            "#", "脚", "状态", "有效", "纳入统计",
            "触地时间(s)", "离地时间(s)", "步长(cm)", "参考点(cm)",
            "两脚间距(cm)", "步速(m/s)", "统计说明",
        ]
        table = QTableWidget(len(steps), len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            "QTableWidget { background-color: rgba(40, 40, 45, 0.8); "
            "border: 1px solid #555; border-radius: 6px; font-size: 10pt; }"
            "QHeaderView::section { background-color: #333; color: #ccc; "
            "border: 1px solid #555; padding: 4px; }"
        )

        for row_idx, step in enumerate(steps):
            items = [
                str(step.index),
                step.side,
                step.row_status,
                "yes" if step.is_event_valid else "no",
                "yes" if step.is_included_in_statistics else "no",
                _fmt(step.contact_time_s),
                _fmt(step.flight_time_s),
                _fmt(step.step_length_cm),
                _fmt(step.step_reference_cm),
                _fmt(step.gap_between_feet_cm),
                _fmt(step.speed_m_s),
                _statistics_note(
                    step.is_included_in_statistics,
                    step.statistics_exclusion_reason,
                    step.quality_flags,
                ),
            ]
            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text or "N/A")
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, col_idx, item)

        # Resize columns
        header = table.horizontalHeader()
        for col in range(len(columns)):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        table.setMinimumHeight(max(len(steps) * 28 + 52, 120))
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._treadmill_step_table = table
        self._add_detail_widget(table)

    def _build_treadmill_metric_summary(self, summaries: dict[str, "MetricSummary"]):
        from qtpy.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

        rows_data = []
        for metric_name, summary in summaries.items():
            display_name = metric_name.replace("_", " ")
            rows_data.append((
                display_name,
                str(summary.count),
                _fmt(summary.mean),
                _fmt(summary.min),
                _fmt(summary.max),
                _fmt(summary.std),
                _fmt(summary.cv_percent),
            ))

        columns = ["指标", "计数", "均值", "最小值", "最大值", "标准差", "CV(%)"]
        table = QTableWidget(len(rows_data), len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            "QTableWidget { background-color: rgba(40, 40, 45, 0.8); "
            "border: 1px solid #555; border-radius: 6px; font-size: 10pt; }"
            "QHeaderView::section { background-color: #333; color: #ccc; "
            "border: 1px solid #555; padding: 4px; }"
        )

        for row_idx, row in enumerate(rows_data):
            for col_idx, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, col_idx, item)

        header = table.horizontalHeader()
        for col in range(len(columns)):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        table.setMinimumHeight(max(len(rows_data) * 28 + 52, 120))
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._add_detail_widget(table)

    def _build_treadmill_left_right(self, lr: dict[str, "MetricSummary"]):
        from qtpy.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

        rows_data = []
        for metric_name, summary in lr.items():
            display_name = metric_name.replace("_", " ")
            rows_data.append((
                display_name,
                str(summary.count),
                _fmt(summary.mean),
                _fmt(summary.min),
                _fmt(summary.max),
                _fmt(summary.std),
                _fmt(summary.cv_percent),
            ))

        if not rows_data:
            return

        columns = ["左右指标", "计数", "均值", "最小值", "最大值", "标准差", "CV(%)"]
        table = QTableWidget(len(rows_data), len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            "QTableWidget { background-color: rgba(40, 40, 45, 0.8); "
            "border: 1px solid #555; border-radius: 6px; font-size: 10pt; }"
            "QHeaderView::section { background-color: #333; color: #ccc; "
            "border: 1px solid #555; padding: 4px; }"
        )

        for row_idx, row in enumerate(rows_data):
            for col_idx, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, col_idx, item)

        header = table.horizontalHeader()
        for col in range(len(columns)):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        table.setMinimumHeight(max(len(rows_data) * 28 + 52, 120))
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._add_detail_widget(table)

    # ------------------------------------------------------------------
    #  辅助方法
    # ------------------------------------------------------------------

    def _clear_dynamic_widgets(self):
        """Remove and delete all dynamically-added widgets to avoid stale tables."""
        for w in self._dynamic_widgets:
            w.setParent(None)
            w.deleteLater()
        self._dynamic_widgets.clear()

    def _add_detail_widget(self, widget: QWidget):
        self._details_layout.addWidget(widget)
        self._dynamic_widgets.append(widget)

    def _fill_stat_cards(self, stats: list[tuple[str, str]]):
        """填充统计卡片。stats 为 (label, value) 列表。"""
        for i, card in enumerate(self._stat_cards):
            if i < len(stats):
                label, value = stats[i]
                card._label.setText(label)
                card.set_value(value)
                card.set_color("#f0f0f0")  # 重置颜色
                card.show()
            else:
                card.hide()
        self._stats_layout.invalidate()
        self._stats_content.adjustSize()
        self._stats_content.updateGeometry()

    def _on_export(self):
        """导出原始帧数据为 Excel。"""
        if self._report is None:
            return

        frames = self._report.export_frames
        timestamps = self._report.export_timestamps
        has_jump_metrics = isinstance(self._report, JumpTestReport) and any(
            (
                self._report.air_times,
                self._report.contact_times,
                self._report.cycle_times,
                self._report.jump_heights,
                self._report.cadences,
            )
        )

        has_treadmill_steps = isinstance(
            self._report, (TreadmillGaitReport, TreadmillRunningReport)
        ) and bool(
            self._report.per_step_results
            or self._report.gait_cycles
            or self._report.raw_gait_events
        )

        if not frames and not has_jump_metrics and not has_treadmill_steps:
            QMessageBox.information(self, "导出", "本次测试无可导出数据。")
            return

        reply = QMessageBox.question(
            self, "导出数据",
            f"本次采集共 {len(frames)} 帧数据，是否保存？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        save_dir = os.path.join(_get_base_dir(), "data")
        os.makedirs(save_dir, exist_ok=True)
        filename = time.strftime("led_frames_%Y%m%d_%H%M%S.xlsx")
        path = os.path.join(save_dir, filename)

        try:
            wb = Workbook()
            default_ws = wb.active
            if frames:
                default_ws.title = "LED Frames"
                default_ws.append(["timestamp", "hex_string"])
                for ts, bits in zip(timestamps, frames):
                    hex_bytes = []
                    for i in range(0, min(96, len(bits)), 8):
                        byte_val = 0
                        for j in range(8):
                            if i + j < len(bits):
                                byte_val |= (bits[i + j] << j)
                        hex_bytes.append(byte_val)
                    hex_str = " ".join(f"{b:02x}" for b in hex_bytes)
                    default_ws.append([ts, hex_str])
            else:
                wb.remove(default_ws)

            if isinstance(self._report, JumpTestReport):
                ws = wb.create_sheet("Jump Metrics")
                ws.append(
                    [
                        "index",
                        "air_time_s",
                        "contact_time_s",
                        "cycle_time_s",
                        "jump_height_m",
                        "cadence_jumps_per_min",
                    ]
                )
                for row in _jump_metric_rows(self._report):
                    ws.append(row)

            if isinstance(self._report, (TreadmillGaitReport, TreadmillRunningReport)):
                # Sheet 2: Treadmill Steps
                ws_steps = wb.create_sheet("Treadmill Steps")
                ws_steps.append(TREADMILL_EXPORT_COLUMNS)
                for row in _treadmill_metric_rows(self._report):
                    ws_steps.append(row)

                if self._report.gait_cycles:
                    ws_cycles = wb.create_sheet("步态周期")
                    ws_cycles.append(GAIT_CYCLE_EXPORT_HEADERS)
                    for row in _gait_cycle_rows(self._report):
                        ws_cycles.append(row)

                if self._report.raw_gait_events:
                    ws_events = wb.create_sheet("原始步态事件")
                    ws_events.append(["序号", "时间(s)", "脚", "事件"])
                    for event in self._report.raw_gait_events:
                        ws_events.append([
                            event.index + 1,
                            event.time_s,
                            _side_label(event.side),
                            "触地" if event.kind == "touch" else "离地",
                        ])

                if self._report.cycle_metric_summaries:
                    ws_cycle_summary = wb.create_sheet("步态周期统计")
                    ws_cycle_summary.append([
                        "指标", "总体数量", "总体均值",
                        "左脚数量", "左脚均值", "右脚数量", "右脚均值",
                        "不对称率(%)",
                    ])
                    for name, summary in self._report.cycle_metric_summaries.items():
                        left = self._report.cycle_side_summaries.get("left", {}).get(name)
                        right = self._report.cycle_side_summaries.get("right", {}).get(name)
                        ws_cycle_summary.append([
                            GAIT_CYCLE_METRIC_LABELS.get(name, name),
                            summary.count, _excel_cycle_value(summary.mean),
                            left.count if left else 0,
                            _excel_cycle_value(left.mean if left else None),
                            right.count if right else 0,
                            _excel_cycle_value(right.mean if right else None),
                            _excel_cycle_value(
                                self._report.cycle_asymmetry_percent.get(name)
                            ),
                        ])

                # Sheet 3 (optional): Metric Summaries
                metric_summaries = self._report.metric_summaries
                if metric_summaries:
                    ws_metrics = wb.create_sheet("Metric Summaries")
                    ws_metrics.append(["metric", "count", "mean", "min", "max", "std", "cv_percent"])
                    for name, sm in metric_summaries.items():
                        ws_metrics.append([
                            name, sm.count,
                            _fmt(sm.mean), _fmt(sm.min), _fmt(sm.max),
                            _fmt(sm.std), _fmt(sm.cv_percent),
                        ])

            wb.save(path)
            QMessageBox.information(self, "导出成功", f"数据已保存至：\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", f"保存文件失败：{e}")


TREADMILL_EXPORT_COLUMNS = [
    "index",
    "side",
    "row_status",
    "is_event_valid",
    "is_included_in_statistics",
    "contact_time_s",
    "flight_time_s",
    "step_time_s",
    "step_length_cm",
    "gap_between_feet_cm",
    "distance_cm",
    "speed_m_s",
    "correction_source",
    "statistics_exclusion_reason",
    "quality_flags",
    "step_reference_cm",
]

GAIT_CYCLE_EXPORT_FIELDS = [
    "index", "side", "start_time_s", "end_time_s", "gait_cycle_s",
    "stance_phase_s", "stance_phase_percent", "swing_phase_s",
    "swing_phase_percent", "step_time_s", "single_support_s",
    "single_support_percent", "total_double_support_s",
    "total_double_support_percent", "load_response_s",
    "load_response_percent", "pre_swing_s", "pre_swing_percent",
    "total_flight_time_s", "is_included_in_statistics",
    "statistics_exclusion_reason", "quality_flags",
]

GAIT_CYCLE_EXPORT_HEADERS = [
    "序号", "脚", "开始时间(s)", "结束时间(s)", "步态周期(s)",
    "支撑相(s)", "支撑相(%)", "摆动相(s)", "摆动相(%)",
    "步时间(s)", "单支撑(s)", "单支撑(%)", "总双支撑(s)",
    "总双支撑(%)", "负荷反应期(s)", "负荷反应期(%)",
    "摆动前期(s)", "摆动前期(%)", "腾空时间(s)", "纳入统计",
    "未纳入原因", "质量提示",
]

GAIT_CYCLE_METRIC_LABELS = {
    "gait_cycle_s": "步态周期 (s)",
    "stance_phase_s": "支撑相 (s)",
    "stance_phase_percent": "支撑相 (%)",
    "swing_phase_s": "摆动相 (s)",
    "swing_phase_percent": "摆动相 (%)",
    "step_time_s": "步时间 (s)",
    "single_support_s": "单支撑 (s)",
    "single_support_percent": "单支撑 (%)",
    "total_double_support_s": "总双支撑 (s)",
    "total_double_support_percent": "总双支撑 (%)",
    "load_response_s": "负荷反应期 (s)",
    "load_response_percent": "负荷反应期 (%)",
    "pre_swing_s": "摆动前期 (s)",
    "pre_swing_percent": "摆动前期 (%)",
    "total_flight_time_s": "腾空时间 (s)",
}


def _jump_metric_rows(report: JumpTestReport) -> list[list[object]]:
    max_len = max(
        len(report.air_times),
        len(report.contact_times),
        len(report.cycle_times),
        len(report.jump_heights),
        len(report.cadences),
        0,
    )
    rows = []
    for index in range(max_len):
        rows.append(
            [
                index + 1,
                _value_at(report.air_times, index),
                _value_at(report.contact_times, index),
                _value_at(report.cycle_times, index),
                _value_at(report.jump_heights, index),
                _value_at(report.cadences, index),
            ]
        )
    return rows


def _value_at(values: tuple, index: int):
    return values[index] if index < len(values) else ""


def _fmt(value: float | None) -> str:
    """Format an optional float value for table display."""
    if value is None:
        return ""
    return f"{value:.3f}"


def _side_label(side: str) -> str:
    return {"left": "左脚", "right": "右脚", "unknown": "未知"}.get(side, side)


def _excel_cycle_value(value):
    return "N/A" if value is None else value


_STATISTICS_REASON_LABELS = {
    "Touch was replaced before lift": "重复触地前未检测到正常离地",
    "Missing same-side lift event": "缺少同侧离地事件",
    "Contact time below minimum threshold": "触地时间低于最小阈值",
    "Flight time outside acceptable range": "腾空时间不在允许范围",
    "Step length below minimum threshold": "步长低于最小阈值",
    "Excluded by automatic_data_filter": "被自动数据过滤排除",
}

_QUALITY_FLAG_LABELS = {
    "gap_below_minimum": "两脚间距低于最小阈值",
    "running_overlap_above_tolerance": "跑步时双脚重叠超过容差",
}


def _statistics_note(
    is_included: bool,
    exclusion_reason: str | None,
    quality_flags: tuple[str, ...],
) -> str:
    parts = []
    if not is_included:
        parts.append(
            f"未纳入：{_statistics_reason_label(exclusion_reason)}"
        )
    if quality_flags:
        parts.append(f"质量提示：{_quality_flags_text(quality_flags)}")
    return "；".join(parts) or "—"


def _statistics_reason_label(reason: str | None) -> str:
    if reason is None:
        return "原因未知"
    return _STATISTICS_REASON_LABELS.get(reason, reason)


def _quality_flags_text(quality_flags: tuple[str, ...]) -> str:
    return "、".join(
        _QUALITY_FLAG_LABELS.get(flag, flag)
        for flag in quality_flags
    )


def _treadmill_metric_rows(report: TreadmillGaitReport | TreadmillRunningReport) -> list[list[object]]:
    """Extract key columns from per_step_results for Excel export and testing."""
    rows = []
    for step in report.per_step_results:
        rows.append(
            [
                step.index,
                step.side,
                step.row_status,
                step.is_event_valid,
                step.is_included_in_statistics,
                _excel_cycle_value(step.contact_time_s),
                _excel_cycle_value(step.flight_time_s),
                _excel_cycle_value(step.step_time_s),
                _excel_cycle_value(step.step_length_cm),
                _excel_cycle_value(step.gap_between_feet_cm),
                _excel_cycle_value(step.distance_cm),
                _excel_cycle_value(step.speed_m_s),
                step.correction_source,
                (
                    _statistics_reason_label(step.statistics_exclusion_reason)
                    if step.statistics_exclusion_reason is not None
                    else "N/A"
                ),
                _quality_flags_text(step.quality_flags) or "N/A",
                _excel_cycle_value(step.step_reference_cm),
            ]
        )
    return rows


def _gait_cycle_rows(report: TreadmillGaitReport | TreadmillRunningReport) -> list[list[object]]:
    rows = []
    for cycle in report.gait_cycles:
        row = [
            _excel_cycle_value(getattr(cycle, name))
            for name in GAIT_CYCLE_EXPORT_FIELDS
        ]
        row[0] = cycle.index + 1
        row[1] = _side_label(cycle.side)
        included_index = GAIT_CYCLE_EXPORT_FIELDS.index(
            "is_included_in_statistics"
        )
        exclusion_reason_index = GAIT_CYCLE_EXPORT_FIELDS.index(
            "statistics_exclusion_reason"
        )
        quality_flags_index = GAIT_CYCLE_EXPORT_FIELDS.index("quality_flags")
        row[included_index] = (
            "是" if cycle.is_included_in_statistics else "否"
        )
        if cycle.statistics_exclusion_reason is not None:
            row[exclusion_reason_index] = _statistics_reason_label(
                cycle.statistics_exclusion_reason
            )
        row[quality_flags_index] = (
            _quality_flags_text(cycle.quality_flags) or "N/A"
        )
        rows.append(row)
    return rows
