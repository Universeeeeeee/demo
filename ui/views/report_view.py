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
import os
import time
from typing import Optional

from openpyxl import Workbook

from qtpy.QtCore import Signal, Qt
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QSizePolicy, QMessageBox, QFileDialog,
)

from dayu_widgets.label import MLabel
from dayu_widgets.divider import MDivider
from dayu_widgets.push_button import MPushButton
from dayu_widgets import dayu_theme

from config.test_report import TestReport, JumpTestReport, GaitTestReport
from path_utils import get_base_dir as _get_base_dir

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

    def set_color(self, color: str):
        self._value.setStyleSheet(
            f"font-size: 26pt; font-weight: bold; "
            f"color: {color}; border: none; background: transparent;"
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
        self._build_ui()

    def _build_ui(self):
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

        # ===== 内容区: 左侧统计 + 右侧图表 =====
        content_layout = QHBoxLayout()
        content_layout.setSpacing(15)

        # --- 左侧: 统计卡片网格 ---
        left_container = QWidget()
        left_container.setMinimumWidth(320)
        self._stats_layout = QGridLayout(left_container)
        self._stats_layout.setContentsMargins(0, 0, 0, 0)
        self._stats_layout.setSpacing(8)

        # 预创建 8 个 StatCard 槽位 (4行x2列)
        self._stat_cards: list[StatCard] = []
        for i in range(8):
            card = StatCard("")
            card.hide()
            row, col = divmod(i, 2)
            self._stats_layout.addWidget(card, row, col)
            self._stat_cards.append(card)

        content_layout.addWidget(left_container, 4)

        # --- 右侧: 图表回顾 ---
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        right_layout.addWidget(MDivider("数据回顾"))

        if _PG_AVAILABLE:
            self._plot_1 = pg.PlotWidget()
            self._plot_1.setBackground(dayu_theme.background_in_color)
            self._plot_1.showGrid(x=True, y=True, alpha=0.1)
            self._plot_1.enableAutoRange()
            right_layout.addWidget(self._plot_1, 1)

            self._plot_2 = pg.PlotWidget()
            self._plot_2.setBackground(dayu_theme.background_in_color)
            self._plot_2.showGrid(x=True, y=True, alpha=0.1)
            self._plot_2.enableAutoRange()
            right_layout.addWidget(self._plot_2, 1)
        else:
            placeholder = QLabel("未安装 pyqtgraph — 图表不可用")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("font-size: 14pt; color: #666;")
            right_layout.addWidget(placeholder)

        content_layout.addWidget(right_container, 6)
        main_layout.addLayout(content_layout, 1)

        # ===== 底部按钮 =====
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        btn_layout.addStretch()

        self.btn_export = MPushButton("📥 导出 Excel")
        self.btn_export.setMinimumHeight(45)
        self.btn_export.setMinimumWidth(160)
        self.btn_export.setStyleSheet("font-size: 14pt; border-radius: 8px;")
        self.btn_export.clicked.connect(self._on_export)
        btn_layout.addWidget(self.btn_export)

        self.btn_home = MPushButton("🏠 返回首页").primary()
        self.btn_home.setMinimumHeight(45)
        self.btn_home.setMinimumWidth(160)
        self.btn_home.setStyleSheet("font-size: 14pt; font-weight: bold; border-radius: 8px;")
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

        if isinstance(report, JumpTestReport):
            self._load_jump_report(report)
        elif isinstance(report, GaitTestReport):
            self._load_gait_report(report)

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
            ("最大腾空", f"{r.max_air_time:.3f} s"),
            ("平均腾空", f"{r.avg_air_time:.3f} s"),
            ("平均触地", f"{r.avg_contact_time:.3f} s"),
            ("平均步频", f"{r.avg_cadence:.1f} spm" if r.avg_cadence else "--"),
        ]
        self._fill_stat_cards(stats)

        # 高亮最大跳高
        if len(self._stat_cards) > 2:
            self._stat_cards[2].set_color(dayu_theme.primary_color)

        # 图表: 全量数据
        if _PG_AVAILABLE and r.air_times:
            heights = [0.5 * G * (t / 2) ** 2 for t in r.air_times]
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
    #  辅助方法
    # ------------------------------------------------------------------

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

    def _on_export(self):
        """导出原始帧数据为 Excel。"""
        if self._report is None:
            return

        frames = self._report.export_frames
        timestamps = self._report.export_timestamps

        if not frames:
            QMessageBox.information(self, "导出", "本次测试无原始帧数据可导出。")
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
            ws = wb.active
            ws.title = "LED Frames"
            ws.append(["timestamp", "hex_string"])
            for ts, bits in zip(timestamps, frames):
                hex_bytes = []
                for i in range(0, min(96, len(bits)), 8):
                    byte_val = 0
                    for j in range(8):
                        if i + j < len(bits):
                            byte_val |= (bits[i + j] << j)
                    hex_bytes.append(byte_val)
                hex_str = " ".join(f"{b:02x}" for b in hex_bytes)
                ws.append([ts, hex_str])
            wb.save(path)
            QMessageBox.information(self, "导出成功", f"数据已保存至：\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", f"保存文件失败：{e}")
