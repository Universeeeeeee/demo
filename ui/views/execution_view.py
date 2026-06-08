"""
execution_view.py — 实时测试核心页

用 MetricCard 仪表盘替代 MTextEdit 纯文本滚动，
支持远距离可读（48pt 大字号）。

设计约束:
  - 不管理 QThread / UsbWorker / GaitEngine
  - 所有数据通过公共方法接收 (on_hop_event, on_gait_snapshot 等)
  - reset() 由 MainWindow 在切入前显式调用
"""

from __future__ import annotations

import importlib
from typing import Optional

from qtpy.QtCore import Signal, Qt, QTimer
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QSizePolicy, QProgressBar,
)

from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton
from dayu_widgets import dayu_theme

from config.test_config import TestConfig

# pyqtgraph 可选导入
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
#  MetricCard — 单个指标仪表盘卡片
# ======================================================================

class MetricCard(QFrame):
    """单个指标卡片: 标题(小字灰色) + 数值(大字高亮) + 单位(小字灰色)"""

    def __init__(self, title: str, unit: str = "", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "MetricCard {"
            "  background-color: rgba(40, 40, 45, 0.85);"
            "  border: 1px solid rgba(80, 80, 85, 0.6);"
            "  border-radius: 10px;"
            "  padding: 8px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignCenter)

        # 标题
        self._title = MLabel(title)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet("font-size: 11pt; color: #888888; border: none; background: transparent;")
        layout.addWidget(self._title)

        # 数值
        self._value = MLabel("--")
        self._value.setAlignment(Qt.AlignCenter)
        self._value.setStyleSheet(
            "font-size: 42pt; font-weight: bold; "
            "color: #f0f0f0; border: none; background: transparent;"
        )
        layout.addWidget(self._value)

        # 单位
        if unit:
            self._unit = MLabel(unit)
            self._unit.setAlignment(Qt.AlignCenter)
            self._unit.setStyleSheet("font-size: 11pt; color: #666666; border: none; background: transparent;")
            layout.addWidget(self._unit)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(120)

    def set_value(self, text: str):
        self._value.setText(text)

    def set_color(self, color: str):
        """设置数值颜色"""
        self._value.setStyleSheet(
            f"font-size: 42pt; font-weight: bold; "
            f"color: {color}; border: none; background: transparent;"
        )


# ======================================================================
#  ExecutionView — 实时测试视图
# ======================================================================

class ExecutionView(QWidget):
    """实时测试核心页 — 仪表盘 + 图表 + 控制栏。"""

    start_requested = Signal()
    pause_requested = Signal()
    stop_requested = Signal()
    camera_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 当前配置
        self._config: Optional[TestConfig] = None
        self._mode: str = "纵跳"

        # 图表数据
        self._h_x, self._h_y = [], []
        self._cadence_x, self._cadence_y = [], []
        self._initial_range = 10
        self._slide_window = 15

        # 实时统计 (从事件中累积)
        self._max_h = 0.0
        self._latest_h = 0.0
        self._latest_cadence = 0.0
        self._touch_count = 0

        # 纵跳事件辅助
        self._last_strike_centroid = None

        # 进度
        self._jump_target: Optional[int] = None
        self._countdown_remaining = 0
        self._countdown_timer: Optional[QTimer] = None

        # 暂停状态
        self._paused = False

        self._build_ui()
        self._apply_style()

    # ------------------------------------------------------------------
    #  UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 10, 15, 10)
        main_layout.setSpacing(10)

        # ===== 顶部状态栏 =====
        top_bar = QHBoxLayout()
        self._mode_label = MLabel("纵跳测试 · 实时")
        self._mode_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #e0e0e0;")
        top_bar.addWidget(self._mode_label)
        top_bar.addStretch()

        # 设备状态
        self._device_label = MLabel("等待连接...")
        self._device_label.setStyleSheet("font-size: 10pt; color: #888888;")
        top_bar.addWidget(self._device_label)

        # 相机按钮组 (三个独立按钮, 各对应固定相机实现)
        self.btn_logi_camera = MPushButton("📷 MX Brio")
        self.btn_logi_camera.setFixedHeight(36)
        self.btn_logi_camera.setStyleSheet(
            "font-size: 11pt; padding: 4px 12px; "
            "background-color: #424242; border: 1px solid #555; border-radius: 6px;"
        )
        self.btn_logi_camera.clicked.connect(lambda: self.camera_requested.emit("logi"))
        top_bar.addWidget(self.btn_logi_camera)

        self.btn_tinyse_camera = MPushButton("🤖 Tiny SE")
        self.btn_tinyse_camera.setFixedHeight(36)
        self.btn_tinyse_camera.setStyleSheet(
            "font-size: 11pt; padding: 4px 12px; "
            "background-color: #424242; border: 1px solid #555; border-radius: 6px;"
        )
        self.btn_tinyse_camera.clicked.connect(lambda: self.camera_requested.emit("tinyse"))
        self.btn_tinyse_camera.setToolTip("OBSBOT Tiny SE (100fps)")
        top_bar.addWidget(self.btn_tinyse_camera)

        self.btn_basic_camera = MPushButton("👁 预览")
        self.btn_basic_camera.setFixedHeight(36)
        self.btn_basic_camera.setStyleSheet(
            "font-size: 11pt; padding: 4px 12px; "
            "background-color: #424242; border: 1px solid #555; border-radius: 6px;"
        )
        self.btn_basic_camera.clicked.connect(lambda: self.camera_requested.emit("basic"))
        top_bar.addWidget(self.btn_basic_camera)

        main_layout.addLayout(top_bar)

        # ===== 仪表盘卡片区 =====
        self._cards_layout = QHBoxLayout()
        self._cards_layout.setSpacing(12)

        # 纵跳模式 4 卡片
        self._card_count = MetricCard("跳跃次数")
        self._card_current = MetricCard("当前跳高", "m")
        self._card_max = MetricCard("最大跳高", "m")
        self._card_cadence = MetricCard("实时步频", "spm")

        self._jump_cards = [self._card_count, self._card_current, self._card_max, self._card_cadence]
        for card in self._jump_cards:
            self._cards_layout.addWidget(card)

        # 步态模式 4 卡片 (初始隐藏)
        self._card_steps = MetricCard("步数")
        self._card_stride = MetricCard("最新步长", "cm")
        self._card_velocity = MetricCard("平均步速", "cm/s")
        self._card_imbalance = MetricCard("不平衡指数", "%")

        self._gait_cards = [self._card_steps, self._card_stride, self._card_velocity, self._card_imbalance]
        for card in self._gait_cards:
            self._cards_layout.addWidget(card)
            card.hide()

        main_layout.addLayout(self._cards_layout)

        # ===== 图表区 =====
        charts_layout = QHBoxLayout()
        charts_layout.setSpacing(10)

        if _PG_AVAILABLE:
            self._plot_h = pg.PlotWidget()
            self._plot_h.setBackground(dayu_theme.background_in_color)
            self._plot_h.showGrid(x=True, y=True, alpha=0.1)
            self._plot_h.setLabel('left', '跳高 h (m)')
            self._plot_h.setLabel('bottom', '跳跃次数')
            self._plot_h.enableAutoRange(axis='y')
            self._plot_h.setXRange(0, 10, padding=0)
            self._h_bar = pg.BarGraphItem(x=[], height=[], width=0.65, brush=dayu_theme.primary_color)
            self._plot_h.addItem(self._h_bar)
            charts_layout.addWidget(self._plot_h, 1)

            self._plot_cadence = pg.PlotWidget()
            self._plot_cadence.setBackground(dayu_theme.background_in_color)
            self._plot_cadence.showGrid(x=True, y=True, alpha=0.1)
            self._plot_cadence.setLabel('left', '步频 (步/分钟)')
            self._plot_cadence.setLabel('bottom', '跳跃次数')
            self._plot_cadence.enableAutoRange(axis='y')
            self._plot_cadence.setXRange(0, 10, padding=0)
            self._cadence_bar = pg.BarGraphItem(x=[], height=[], width=0.65, brush='#52c41a')
            self._plot_cadence.addItem(self._cadence_bar)
            charts_layout.addWidget(self._plot_cadence, 1)
        else:
            placeholder = QLabel("未安装 pyqtgraph — 图表不可用")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("font-size: 14pt; color: #666;")
            charts_layout.addWidget(placeholder)

        main_layout.addLayout(charts_layout, 1)

        # ===== 进度条 =====
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("")
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(28)
        self._progress_bar.setStyleSheet(
            "QProgressBar {"
            "  background-color: rgba(40, 40, 45, 0.8);"
            "  border: 1px solid #444;"
            "  border-radius: 6px;"
            "  text-align: center;"
            "  color: #e0e0e0;"
            "  font-size: 11pt;"
            "}"
            "QProgressBar::chunk {"
            "  background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "    stop:0 #1890ff, stop:1 #36cfc9);"
            "  border-radius: 5px;"
            "}"
        )
        self._progress_bar.hide()
        main_layout.addWidget(self._progress_bar)

        # ===== 控制按钮栏 =====
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.btn_start = MPushButton("▶ 开始采集").primary()
        self.btn_start.setMinimumHeight(50)
        self.btn_start.setStyleSheet("font-size: 16pt; font-weight: bold; border-radius: 8px;")
        self.btn_start.clicked.connect(self._on_start)
        btn_layout.addWidget(self.btn_start)

        self.btn_pause = MPushButton("⏸ 暂停")
        self.btn_pause.setMinimumHeight(50)
        self.btn_pause.setStyleSheet("font-size: 14pt; border-radius: 8px;")
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_pause.hide()
        btn_layout.addWidget(self.btn_pause)

        self.btn_stop = MPushButton("⏹ 结束并生成报告")
        self.btn_stop.setMinimumHeight(50)
        self.btn_stop.setStyleSheet("font-size: 14pt; border-radius: 8px;")
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_stop.hide()
        btn_layout.addWidget(self.btn_stop)

        main_layout.addLayout(btn_layout)

    def _apply_style(self):
        self.setStyleSheet(
            "QWidget { font-family: 'Microsoft YaHei UI', sans-serif; }"
        )

    # ------------------------------------------------------------------
    #  公共接口 (被 MainWindow / SessionController 调用)
    # ------------------------------------------------------------------

    def configure(self, config: TestConfig):
        """切入本视图前调用，初始化仪表盘标签和图表轴。"""
        self._config = config
        self._mode = "纵跳" if config.test_type == "Jump Test" else "步态分析"

        # 切换模式标签
        mode_text = "纵跳测试" if self._mode == "纵跳" else "步态分析"
        self._mode_label.setText(f"{mode_text} · 就绪")

        # 切换卡片可见性
        is_jump = self._mode == "纵跳"
        for c in self._jump_cards:
            c.setVisible(is_jump)
        for c in self._gait_cards:
            c.setVisible(not is_jump)

        # 切换图表标签
        if _PG_AVAILABLE:
            if is_jump:
                self._plot_h.setLabel('left', '跳高 h (m)')
                self._plot_h.setLabel('bottom', '跳跃次数')
                self._plot_cadence.setLabel('left', '步频 (步/分钟)')
                self._plot_cadence.setLabel('bottom', '跳跃次数')
            else:
                self._plot_h.setLabel('left', '步长 (cm)')
                self._plot_h.setLabel('bottom', '步数')
                self._plot_cadence.setLabel('left', '步速 (cm/s)')
                self._plot_cadence.setLabel('bottom', '步数')

        # 初始化进度
        self._init_progress(config)

        # 按钮状态: 显示"开始"
        self.btn_start.show()
        self.btn_pause.hide()
        self.btn_stop.hide()
        self._device_label.setText("等待连接...")

    def set_tinyse_available(self, available: bool):
        """由 MainWindow 调用, 更新 Tiny SE 按钮提示."""
        if available:
            self.btn_tinyse_camera.setToolTip("OBSBOT Tiny SE (已检测到)")
        else:
            self.btn_tinyse_camera.setToolTip("OBSBOT Tiny SE (未检测到，点击可重试)")

    def reset(self):
        """重置所有仪表盘和图表到初始状态。"""
        # 仪表盘
        for card in self._jump_cards + self._gait_cards:
            card.set_value("--")
            card.set_color("#f0f0f0")

        # 图表数据
        self._h_x, self._h_y = [], []
        self._cadence_x, self._cadence_y = [], []
        if _PG_AVAILABLE:
            self._h_bar.setOpts(x=[], height=[])
            self._cadence_bar.setOpts(x=[], height=[])
            self._plot_h.setXRange(0, self._initial_range, padding=0)
            self._plot_cadence.setXRange(0, self._initial_range, padding=0)

        # 实时统计
        self._max_h = 0.0
        self._latest_h = 0.0
        self._latest_cadence = 0.0
        self._touch_count = 0
        self._last_strike_centroid = None
        self._paused = False

        # 进度
        self._stop_countdown()
        self._progress_bar.hide()
        self._progress_bar.setValue(0)

    def on_hop_event(self, ev):
        """接收纵跳事件，更新仪表盘 + 图表。"""
        air_time = getattr(ev, '_air_time', None)
        if ev.kind.lower() == "touch" and air_time is not None:
            h = ev._hop_height
            contact_time = getattr(ev, '_contact_time', None)

            # 更新统计
            self._touch_count += 1
            self._latest_h = h
            if h > self._max_h:
                self._max_h = h

            # 计算步频
            if contact_time is not None and contact_time > 0:
                cadence = 60.0 / (air_time + contact_time)
            else:
                cadence = 60.0 / air_time if air_time > 0 else 0
            self._latest_cadence = cadence

            # 更新仪表盘
            target_str = f"/{self._jump_target}" if self._jump_target else ""
            self._card_count.set_value(f"{self._touch_count}{target_str}")
            self._card_current.set_value(f"{h:.3f}")
            self._card_max.set_value(f"{self._max_h:.3f}")
            self._card_max.set_color(dayu_theme.primary_color)
            self._card_cadence.set_value(f"{cadence:.0f}")

            # 更新图表
            self._update_charts(h, cadence)

            # 更新进度
            self._update_jump_progress()

        # 记录质心
        if ev.kind.lower() == "touch" and ev.centroid_cm:
            self._last_strike_centroid = ev.centroid_cm

    def on_gait_step_event(self, ev):
        """接收步态事件，更新图表。"""
        if ev.kind == "touch" and ev.contact.step_length is not None:
            self._update_charts(ev.contact.step_length, ev.contact.velocity)

    def on_gait_snapshot(self, snapshot: dict):
        """接收步态快照 (~10Hz)，更新仪表盘。"""
        self._card_steps.set_value(str(snapshot['touch_count']))

        if snapshot.get("stride_count", 0) > 0:
            latest = snapshot.get("latest_stride", 0)
            self._card_stride.set_value(f"{latest:.1f}")

        if snapshot.get("velocity_count", 0) > 0:
            avg_vel = snapshot["velocity_sum"] / snapshot["velocity_count"]
            self._card_velocity.set_value(f"{avg_vel:.1f}")

        em = snapshot.get("latest_extra_metrics", {})
        if em and em.get("imbalance_index") is not None:
            self._card_imbalance.set_value(f"{em['imbalance_index']:.1f}")

    def on_device_message(self, msg: str):
        """显示设备状态。"""
        self._device_label.setText(msg[:50])

    # ------------------------------------------------------------------
    #  图表更新 (从 data_show.py 迁移)
    # ------------------------------------------------------------------

    def _update_charts(self, val1: float, val2: float):
        """更新两个柱状图。"""
        if not _PG_AVAILABLE:
            return

        self._h_x.append(len(self._h_x) + 1)
        self._h_y.append(val1)
        self._cadence_x.append(len(self._cadence_x) + 1)
        self._cadence_y.append(val2)

        # 滑动窗口
        sw = self._slide_window
        dh_x = self._h_x[-sw:] if len(self._h_x) > sw else self._h_x
        dh_y = self._h_y[-sw:] if len(self._h_y) > sw else self._h_y
        dc_x = self._cadence_x[-sw:] if len(self._cadence_x) > sw else self._cadence_x
        dc_y = self._cadence_y[-sw:] if len(self._cadence_y) > sw else self._cadence_y

        self._h_bar.setOpts(x=dh_x, height=dh_y, width=0.65, brush=dayu_theme.primary_color)
        self._cadence_bar.setOpts(x=dc_x, height=dc_y, width=0.65, brush='#52c41a')

        # X 轴范围
        idx = len(self._h_x)
        if idx <= self._initial_range:
            self._plot_h.setXRange(0, self._initial_range, padding=0)
            self._plot_cadence.setXRange(0, self._initial_range, padding=0)
        else:
            x_max = idx + 0.5
            x_min = max(0, idx - sw + 0.5)
            self._plot_h.setXRange(x_min, x_max, padding=0)
            self._plot_cadence.setXRange(x_min, x_max, padding=0)

    # ------------------------------------------------------------------
    #  进度显示
    # ------------------------------------------------------------------

    def _init_progress(self, config: TestConfig):
        """初始化进度条。"""
        self._stop_countdown()
        self._jump_target = None

        if config.stop_type == "Status change" and config.number_of_jumps:
            self._jump_target = config.number_of_jumps
            self._progress_bar.setMaximum(self._jump_target)
            self._progress_bar.setValue(0)
            self._progress_bar.setFormat(f"0 / {self._jump_target} 跳")
            self._progress_bar.show()
        elif config.stop_type == "End of Time" and config.test_length:
            total = config.get_test_length_seconds() or 0
            self._countdown_remaining = total
            self._progress_bar.setMaximum(total)
            self._progress_bar.setValue(total)
            mm, ss = divmod(total, 60)
            self._progress_bar.setFormat(f"剩余 {mm:02d}:{ss:02d}")
            self._progress_bar.show()
        else:
            self._progress_bar.hide()

    def _start_countdown(self):
        """启动倒计时定时器（在"开始采集"后调用）。"""
        if self._countdown_remaining > 0:
            self._countdown_timer = QTimer(self)
            self._countdown_timer.timeout.connect(self._on_countdown_tick)
            self._countdown_timer.start(1000)

    def _on_countdown_tick(self):
        self._countdown_remaining -= 1
        if self._countdown_remaining <= 0:
            self._stop_countdown()
            self._progress_bar.setFormat("时间到")
            self._progress_bar.setValue(0)
        else:
            mm, ss = divmod(self._countdown_remaining, 60)
            self._progress_bar.setFormat(f"剩余 {mm:02d}:{ss:02d}")
            total = self._progress_bar.maximum()
            self._progress_bar.setValue(self._countdown_remaining)

    def _update_jump_progress(self):
        if self._jump_target is None:
            return
        self._progress_bar.setValue(self._touch_count)
        self._progress_bar.setFormat(f"{self._touch_count} / {self._jump_target} 跳")

    def _stop_countdown(self):
        if self._countdown_timer:
            self._countdown_timer.stop()
            self._countdown_timer = None

    # ------------------------------------------------------------------
    #  按钮事件
    # ------------------------------------------------------------------

    def _on_start(self):
        self._mode_label.setText(
            f"{'纵跳测试' if self._mode == '纵跳' else '步态分析'} · 运行中"
        )
        self.btn_start.hide()
        self.btn_pause.show()
        self.btn_stop.show()
        self._start_countdown()
        self.start_requested.emit()

    def _on_pause(self):
        if not self._paused:
            self._paused = True
            self.btn_pause.setText("▶ 继续")
            self._mode_label.setText(
                f"{'纵跳测试' if self._mode == '纵跳' else '步态分析'} · 已暂停"
            )
        else:
            self._paused = False
            self.btn_pause.setText("⏸ 暂停")
            self._mode_label.setText(
                f"{'纵跳测试' if self._mode == '纵跳' else '步态分析'} · 运行中"
            )
        self.pause_requested.emit()

    def _on_stop(self):
        self._stop_countdown()
        self.stop_requested.emit()
