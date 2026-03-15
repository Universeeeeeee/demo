"""
2data_show.py - 实时步态分析前端

完全复用 1data_show.py 的计算方案:
- 使用 SingleFootDetector.consume() 进行流式事件检测
- 使用相同的跳高/步频公式
- 数据源从 NPZ 文件变为 USB 实时采集
"""
from __future__ import annotations

import importlib
import os
import time

from qtpy import QtWidgets
from qtpy.QtCore import QThread, Qt
from qtpy.QtGui import QTextCursor, QTextBlockFormat
from dayu_widgets.divider import MDivider
from dayu_widgets.push_button import MPushButton
from dayu_widgets.text_edit import MTextEdit
from dayu_widgets import dayu_theme
from dayu_widgets.qt import application

# 直接从 start_test.py 导入 UsbWorker
try:
    from .start_test import UsbWorker
    from .single_leg_hop_npz_parser import SingleFootDetector, LedFrame, FootEvent
    from .gait_npz_parser import ClusterTracker, extract_clusters, LedFrame as GaitLedFrame
    from .camera import Camera
except ImportError:
    from start_test import UsbWorker
    from single_leg_hop_npz_parser import SingleFootDetector, LedFrame, FootEvent
    from gait_npz_parser import ClusterTracker, extract_clusters, LedFrame as GaitLedFrame
    from camera import Camera

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

G = 9.81  # 重力加速度


class RealTimeGaitWidget(QtWidgets.QWidget):
    """
    实时步态分析界面。
    
    完全复用 1data_show.py 的计算方案:
    - SingleFootDetector.consume(frame) 进行流式事件检测
    - 相同的跳高公式: h = 0.5 * G * (air_time / 2) ** 2
    - 相同的步频公式: cadence = 60 / (air_time + contact_time)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.paused = False
        
        # 模式: "纵跳" 或 "步态分析"
        self.current_mode = "纵跳"
        
        # 图表数据 (与 1data_show.py 完全一致)
        self.h_x, self.h_y = [], []
        self.cadence_x, self.cadence_y = [], []
        self.initial_range = 10
        self.slide_window = 15

        # 统计数据 (与 1data_show.py 完全一致)
        self.touch_count = 0
        self.lift_count = 0
        self.last_touch_time = None
        self.last_lift_time = None
        self._last_strike_centroid = None
        self.cycle_times = []
        self.air_times = []
        self.contact_times = []
        
        # 步态分析专用数据
        self.stride_lengths = []  # 步幅 (cm)
        self.velocities = []  # 步速 (cm/s)
        self._current_foot = "A"  # 交替 A/B
        self._foot_a_support_times = []  # Foot A 支撑时间
        self._foot_b_support_times = []  # Foot B 支撑时间
        self._foot_touch_time = {"A": None, "B": None}  # 各脚触地时间
        
        # ===== 性能优化: UI 节流 =====
        self._last_ui_update = 0.0  # 上次 UI 更新时间
        self._ui_update_interval = 0.1  # UI 更新间隔 (100ms = 10Hz)
        self._last_chart_update = 0.0  # 上次图表更新时间
        self._chart_update_interval = 0.15  # 图表更新间隔 (150ms)
        self._pending_chart_data = None  # 待更新的图表数据
        
        # ===== 性能优化: 增量统计 =====
        self._stride_sum = 0.0
        self._stride_count = 0
        self._velocity_sum = 0.0
        self._velocity_count = 0
        self._air_time_sum = 0.0
        self._air_time_count = 0
        self._contact_time_sum = 0.0
        self._contact_time_count = 0
        self._foot_a_support_sum = 0.0
        self._foot_b_support_sum = 0.0
        
        # ===== 性能优化: 行距设置标记 =====
        self._line_spacing_applied = False
        
        # 相机实例
        self.camera = None
        
        # 事件检测器 (纵跳模式)
        self.detector = None
        
        # 步态追踪器 (步态分析模式)
        self.gait_tracker = None

        # USB 配置
        self.dll_path = os.getenv(
            "DAYU_DLL",
            "CyUsbInterface.dll",
        )
        self.vid = self._parse_int_env("DAYU_VID", 0x04B4)
        self.pid = self._parse_int_env("DAYU_PID", 0x1004)
        self.timeout_ms = self._parse_int_env("DAYU_TIMEOUT", 30)
        self.chunk_size = self._parse_int_env("DAYU_CHUNK", 512)
        
        # Worker 和线程
        self.serial_thread = None
        self.serial_worker = None
        
        # 时间基准
        self._start_time = None

        self._init_ui()
        self._apply_global_style()
        self.setWindowTitle("运动步态分析系统")
        self.setMinimumSize(1000, 600)
        self.resize(1000, 600)

    @staticmethod
    def _parse_int_env(name, default):
        v = os.getenv(name)
        if not v:
            return default
        try:
            return int(v, 0)
        except Exception:
            return default

    def _init_ui(self):
        """UI 布局 - 优化版"""
        self.main_lay = QtWidgets.QHBoxLayout()
        
        # 左侧面板容器 - 添加内边距
        left_container = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_container)
        left_layout.setContentsMargins(15, 10, 15, 10)  # 左右内边距 15px

        # 模式选择
        left_layout.addWidget(MDivider("模式选择"))
        # 使用标准 QComboBox 替代 MComboBox 以获得稳定的点击行为
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["纵跳", "步态分析"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)
        self.mode_combo.setObjectName("modeCombo")
        self.mode_combo.setMinimumHeight(32)
        left_layout.addWidget(self.mode_combo)

        # 分析详情
        left_layout.addWidget(MDivider("分析详情"))
        self.text_edit_top = MTextEdit(self)
        self.text_edit_top.setReadOnly(True)
        self.text_edit_top.setMinimumSize(200, 300)
        self.text_edit_top.setObjectName("data_display_edit")
        self.text_edit_top.setStyleSheet("QTextEdit#data_display_edit { font-size: 14pt; }")
        self.text_edit_top.setText("请选择模式并点击 开始分析 按钮...")  # 默认提示文案
        left_layout.addWidget(self.text_edit_top, 1)

        # 按钮区 - 重新布局：相机按钮 + 开始分析按钮
        left_layout.addWidget(MDivider("操作"))
        self.btn_container = QtWidgets.QWidget()
        self.btn_container.setMinimumHeight(120)  # 增加高度容纳两个按钮
        self.btn_layout = QtWidgets.QVBoxLayout(self.btn_container)  # 改为垂直布局
        self.btn_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_layout.setSpacing(10)
        
        # 相机按钮 (次级样式)
        self.btn_camera = MPushButton("📷 打开相机")
        self.btn_camera.setObjectName("btnCamera")
        self.btn_camera.setMinimumHeight(45)
        self.btn_camera.clicked.connect(self.on_camera_clicked)
        self.btn_layout.addWidget(self.btn_camera)
        
        # 开始分析按钮 (主要样式)
        self.btn_start = MPushButton("开始分析").primary()
        self.btn_start.setObjectName("btnStart")
        self.btn_start.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.btn_start.setMinimumHeight(60)
        self.btn_start.clicked.connect(self.on_start_clicked)
        self.btn_layout.addWidget(self.btn_start)
        left_layout.addWidget(self.btn_container, 0)

        # 右侧图表 (与 1data_show.py 完全一致)
        right_layout = QtWidgets.QVBoxLayout()
        right_layout.addWidget(MDivider("数据可视化"))

        if _PG_AVAILABLE:
            # 图表1: 跳高
            self.plot_widget = pg.PlotWidget()
            self.plot_widget.setBackground(dayu_theme.background_in_color)
            self.plot_widget.showGrid(x=True, y=True, alpha=0.1)  # 降低网格透明度
            self.plot_widget.setLabel('left', '跳高 h (m)')
            self.plot_widget.setLabel('bottom', '跳跃次数')
            self.plot_widget.enableAutoRange(axis='y')
            self.plot_widget.setXRange(0, 10, padding=0)
            self.h_bar = pg.BarGraphItem(x=[], height=[], width=0.65, brush=dayu_theme.primary_color)
            self.plot_widget.addItem(self.h_bar)
            right_layout.addWidget(self.plot_widget, 1)

            # 图表2: 步频
            self.plot_widget_cadence = pg.PlotWidget()
            self.plot_widget_cadence.setBackground(dayu_theme.background_in_color)
            self.plot_widget_cadence.showGrid(x=True, y=True, alpha=0.1)  # 降低网格透明度
            self.plot_widget_cadence.setLabel('left', '步频 (步/分钟)')
            self.plot_widget_cadence.setLabel('bottom', '跳跃次数')
            self.plot_widget_cadence.enableAutoRange(axis='y')
            self.plot_widget_cadence.setXRange(0, 10, padding=0)
            self.cadence_bar = pg.BarGraphItem(x=[], height=[], width=0.65, brush='#52c41a')
            self.plot_widget_cadence.addItem(self.cadence_bar)
            right_layout.addWidget(self.plot_widget_cadence, 1)
        else:
            placeholder = QtWidgets.QLabel("未安装 pyqtgraph")
            right_layout.addWidget(placeholder)

        self.main_lay.addWidget(left_container, 1)  # 使用容器
        self.main_lay.addLayout(right_layout, 2)
        self.setLayout(self.main_lay)

    def _apply_global_style(self):
        """应用全局 QSS 样式表"""
        style = """
        /* 全局字体 */
        QWidget {
            font-family: "Microsoft YaHei UI", "微软雅黑", sans-serif;
        }
        
        /* 相机按钮 - 次级样式 */
        QPushButton#btnCamera {
            background-color: #424242;
            color: #e0e0e0;
            border-radius: 6px;
            font-size: 14px;
            padding: 8px;
            border: 1px solid #555555;
        }
        QPushButton#btnCamera:hover {
            background-color: #505050;
            border-color: #777777;
        }
        QPushButton#btnCamera:pressed {
            background-color: #383838;
        }
        
        /* 主操作按钮 - 增强样式 */
        QPushButton#btnStart {
            border-radius: 6px;
            font-size: 20px;
        }
        
        /* 模式选择下拉框样式 */
        QComboBox#modeCombo {
            background-color: #3a3a3a;
            color: #e0e0e0;
            border: 1px solid #555555;
            border-radius: 4px;
            padding: 6px 12px;
            font-size: 14px;
        }
        QComboBox#modeCombo:hover {
            border-color: #777777;
            background-color: #454545;
        }
        QComboBox#modeCombo:focus {
            border-color: #555555;
            background-color: #3a3a3a;
        }
        QComboBox#modeCombo:on {
            border-color: #555555;
            background-color: #3a3a3a;
        }
        QComboBox#modeCombo::drop-down {
            border: none;
            width: 20px;
        }
        QComboBox#modeCombo QAbstractItemView {
            background-color: #3a3a3a;
            color: #e0e0e0;
            selection-background-color: #4a4a4a;
            border: 1px solid #555555;
        }
        """
        self.setStyleSheet(style)
    
    def on_camera_clicked(self):
        """打开/关闭相机"""
        if self.camera is None:
            self.camera = Camera()
        
        if not self.camera.is_running:
            self.camera.open_camera(threaded=True)
            self.btn_camera.setText("📷 关闭相机")
        else:
            self.camera.close_camera()
            self.btn_camera.setText("📷 打开相机")

    def on_mode_changed(self, text):
        """模式切换 - 中文版"""
        self.current_mode = text
        if text == "纵跳":
            if _PG_AVAILABLE:
                self.plot_widget.setLabel('left', '跳高 h (m)')
                self.plot_widget.setLabel('bottom', '跳跃次数')
                self.plot_widget_cadence.setLabel('left', '步频 (步/分钟)')
                self.plot_widget_cadence.setLabel('bottom', '跳跃次数')
        else:
            if _PG_AVAILABLE:
                self.plot_widget.setLabel('left', '步幅 (cm)')
                self.plot_widget.setLabel('bottom', '步数')
                self.plot_widget_cadence.setLabel('left', '步速 (cm/s)')
                self.plot_widget_cadence.setLabel('bottom', '步数')
        self._reset_analysis_state()
        # 清空分析详情并显示默认提示
        self.text_edit_top.setText(f"已切换至: {text} 模式\n请点击 开始分析 按钮...")

    def _reset_analysis_state(self):
        """重置分析状态"""
        self.touch_count = 0
        self.lift_count = 0
        self.last_touch_time = None
        self.last_lift_time = None
        self._last_strike_centroid = None
        self.cycle_times = []
        self.air_times = []
        self.contact_times = []
        # 步态分析专用数据重置
        self.stride_lengths = []
        self.velocities = []
        self._current_foot = "A"
        self._foot_a_support_times = []
        self._foot_b_support_times = []
        self._foot_touch_time = {"A": None, "B": None}
        # ClusterTracker 状态重置（含去抖）
        self._prev_cluster_count = 0
        self._confirmed_cluster_count = 0
        self._touch_streak = 0
        self._lift_streak = 0
        self._pending_clusters = []
        self._last_valid_step_time = 0.0
        
        # ===== 性能优化: 重置 UI 节流状态 =====
        self._last_ui_update = 0.0
        self._last_chart_update = 0.0
        self._pending_chart_data = None
        
        # ===== 性能优化: 重置增量统计 =====
        self._stride_sum = 0.0
        self._stride_count = 0
        self._velocity_sum = 0.0
        self._velocity_count = 0
        self._air_time_sum = 0.0
        self._air_time_count = 0
        self._contact_time_sum = 0.0
        self._contact_time_count = 0
        self._foot_a_support_sum = 0.0
        self._foot_b_support_sum = 0.0
        self._line_spacing_applied = False
        
        if _PG_AVAILABLE:
            self.h_x, self.h_y = [], []
            self.cadence_x, self.cadence_y = [], []
            self.h_bar.setOpts(x=[], height=[])
            self.cadence_bar.setOpts(x=[], height=[])
            self.plot_widget.setXRange(0, self.initial_range, padding=0)
            self.plot_widget_cadence.setXRange(0, self.initial_range, padding=0)

    def on_start_clicked(self):
        """开始采集 (复用 start_test.py 的 USB 启动逻辑)"""
        self.paused = False
        self.btn_start.setVisible(False)
        self.mode_combo.setEnabled(False)

        # 创建暂停/结束按钮
        self.btn_pause = MPushButton("暂停")
        self.btn_pause.setMinimumHeight(60)
        self.btn_stop = MPushButton("结束")
        self.btn_stop.setMinimumHeight(60)
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.btn_layout.addWidget(self.btn_pause)
        self.btn_layout.addWidget(self.btn_stop)

        # 重置状态
        self._reset_analysis_state()
        self._start_time = time.perf_counter()
        
        # 根据模式初始化检测器/追踪器
        if self.current_mode == "纵跳":
            # 纵跳模式: 使用 SingleFootDetector
            self.detector = SingleFootDetector(
                touch_ratio_threshold=0.12,
                lift_ratio_threshold=0.05,
                confirm_samples=2
            )
            self.gait_tracker = None
        else:
            # 步态分析模式: 使用 ClusterTracker
            self.gait_tracker = ClusterTracker()
            self.detector = None
        
        mode_text = "纵跳" if self.current_mode == "纵跳" else "步态分析"
        self.text_edit_top.setText(f"模式: {mode_text} (实时)\n正在连接设备...")
        self._apply_line_spacing(self.text_edit_top, 140)

        # 启动 USB Worker
        self.serial_worker = UsbWorker(
            dll_path=self.dll_path,
            vid=self.vid,
            pid=self.pid,
            timeout_ms=self.timeout_ms,
            chunk_size=self.chunk_size,
        )
        self.serial_thread = QThread()
        self.serial_worker.moveToThread(self.serial_thread)
        self.serial_thread.started.connect(self.serial_worker.start)
        # 连接 LED 信号到实时处理函数
        self.serial_worker.led_bits_signal.connect(self._on_led_bits_received)
        self.serial_worker.data_received.connect(self._on_device_message)
        self.serial_thread.finished.connect(self.serial_worker.deleteLater)
        self.serial_thread.start()

    def _apply_line_spacing(self, edit, percent=150):
        """设置行距 - 性能优化：只在首次调用时应用"""
        if self._line_spacing_applied:
            return  # 已设置过，跳过
        cursor = edit.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)
        fmt = QTextBlockFormat()
        fmt.setLineHeight(float(percent), 1)
        cursor.mergeBlockFormat(fmt)
        cursor.endEditBlock()
        self._line_spacing_applied = True

    def _on_device_message(self, msg: str):
        """显示设备消息"""
        current = self.text_edit_top.toPlainText()
        if "正在连接设备" in current:
            self.text_edit_top.setText(f"设备: {msg}\n等待数据...")
        self._apply_line_spacing(self.text_edit_top, 140)

    def _on_led_bits_received(self, bits: list):
        """
        实时处理 LED 帧
        
        纵跳模式: 使用 SingleFootDetector.consume()
        步态分析模式: 使用 ClusterTracker.update() 进行多簇追踪
        
        重要: USB 位图语义需要反转以匹配 NPZ 解析器:
        - USB 原始: 1 = LED 亮 (未遮挡)
        - NPZ/Detector 期望: 1 = 遮挡 (触地)
        """
        if self.paused:
            return

        # 关键：位图语义反转 (与 NpzFrameReader._bytes_to_bits() 中的 [1-x for x in bits] 一致)
        # 使得 1 = 遮挡/触地，0 = 未遮挡
        bits = [1 - b for b in bits]

        # 计算当前帧的时间戳
        current_time = time.perf_counter()
        timestamp = current_time - self._start_time if self._start_time else 0
        
        if self.current_mode == "纵跳":
            # 纵跳模式: 使用 SingleFootDetector
            frame = LedFrame(timestamp=timestamp, bits=bits)
            for ev in self.detector.consume(frame):
                self._process_hop_event(ev)
        else:
            # 步态分析模式: 使用 ClusterTracker 进行多簇追踪
            clusters = extract_clusters(bits)
            self.gait_tracker.update(timestamp, clusters)
            self._process_gait_clusters(timestamp, clusters)

    def _process_hop_event(self, ev: FootEvent):
        """
        处理跳跃事件 (与 1data_show.py 中的 _process_hop_event 完全一致)
        """
        if ev.kind.lower() == "touch":
            self.touch_count += 1
            if self.last_lift_time is not None:
                air_time = ev.time - self.last_lift_time
                if air_time > 0:
                    self.air_times.append(air_time)
                    # 跳高公式 (与 1data_show.py 完全一致)
                    h = 0.5 * G * (air_time / 2) ** 2
                    # 获取最新的 contact_time 用于计算步频
                    contact_time = self.contact_times[-1] if self.contact_times else None
                    self._update_charts(h, air_time, contact_time)
            if self.last_touch_time is not None:
                cycle = ev.time - self.last_touch_time
                if cycle > 0:
                    self.cycle_times.append(cycle)
            self.last_touch_time = ev.time
        elif ev.kind.lower() == "lift":
            self.lift_count += 1
            if self.last_touch_time is not None:
                contact_time = ev.time - self.last_touch_time
                if contact_time > 0:
                    self.contact_times.append(contact_time)
            self.last_lift_time = ev.time
        self._update_display(ev)

    def _process_gait_event(self, ev: FootEvent):
        """
        处理步态事件 - 增强版，跟踪 Foot A/B 和支撑时间
        """
        if ev.kind.lower() == "touch":
            self.touch_count += 1
            
            # 交替脚标识
            if self.touch_count % 2 == 1:
                self._current_foot = "A"
            else:
                self._current_foot = "B"
            
            # 记录该脚触地时间
            self._foot_touch_time[self._current_foot] = ev.time
            
            # 计算步长和步速
            if self.last_touch_time is not None and self._last_strike_centroid is not None:
                step_length = abs(ev.centroid_cm - self._last_strike_centroid) if ev.centroid_cm else 0
                step_time = ev.time - self.last_touch_time
                velocity = step_length / step_time if step_time > 0 else 0
                
                if step_length > 0:
                    self.stride_lengths.append(step_length)
                    self.velocities.append(velocity)
                    self._update_charts(step_length, velocity, None)
            
            self.last_touch_time = ev.time
            self._last_strike_centroid = ev.centroid_cm
            
        elif ev.kind.lower() == "lift":
            self.lift_count += 1
            
            # 修复：直接使用当前脚 (self._current_foot) 计算支撑时间
            # 支撑时间 = 同一只脚从触地到离地的时间间隔
            target_foot = self._current_foot
            touch_time = self._foot_touch_time.get(target_foot)
            
            if touch_time is not None:
                support_time = ev.time - touch_time
                if support_time > 0:
                    if target_foot == "A":
                        self._foot_a_support_times.append(support_time)
                    else:
                        self._foot_b_support_times.append(support_time)
            
        self._update_display(ev)

    def _process_gait_clusters(self, timestamp: float, clusters: list):
        """
        基于 ClusterTracker 的实时步态分析（带去抖）。
        
        使用 confirm_samples 机制：簇数量变化需要持续 N 帧才确认为有效事件。
        - 簇数量增加 → 新的触地事件（需确认）
        - 簇数量减少 → 离地事件（需确认）
        """
        # 去抖参数
        CONFIRM_SAMPLES = 30  # 30帧 @ 1000Hz = 30ms 防抖
        MIN_STEP_INTERVAL = 0.3  # 最小步态间隔 300ms
        
        # 获取当前活跃簇数量
        active_count = len(clusters)
        
        # 初始化状态（如果还没有）
        if not hasattr(self, '_prev_cluster_count'):
            self._prev_cluster_count = 0
            self._confirmed_cluster_count = 0  # 已确认的簇数量
            self._touch_streak = 0  # 触地确认计数
            self._lift_streak = 0   # 离地确认计数
            self._pending_clusters = []  # 待确认的簇列表
            self._last_valid_step_time = 0.0 # 上次有效步态时间
        
        # 检测簇数量变化趋势
        if active_count > self._confirmed_cluster_count:
            # 簇数量增加趋势 → 可能是触地
            self._touch_streak += 1
            self._lift_streak = max(0, self._lift_streak - 1)
            self._pending_clusters = clusters  # 保存待确认的簇
            
            if self._touch_streak >= CONFIRM_SAMPLES:
                # [新增] 最小时间间隔检查
                if timestamp - self._last_valid_step_time < MIN_STEP_INTERVAL:
                    # 冷却时间内，视为抖动/分裂，更新状态以同步物理现实，但不计步
                    self._confirmed_cluster_count = active_count
                    self._touch_streak = 0
                    return 

                self._last_valid_step_time = timestamp
                # 确认触地事件
                self._confirmed_cluster_count = active_count
                self._touch_streak = 0
                
                # 处理新增的簇
                for cluster in self._pending_clusters:
                    self.touch_count += 1
                    
                    # 交替脚标识
                    self._current_foot = "A" if self.touch_count % 2 == 1 else "B"
                    
                    # 记录触地时间
                    self._foot_touch_time[self._current_foot] = timestamp
                    
                    # 计算步幅和步速
                    if self.last_touch_time is not None and self._last_strike_centroid is not None:
                        step_length = abs(cluster.centroid_cm - self._last_strike_centroid)
                        step_time = timestamp - self.last_touch_time
                        velocity = step_length / step_time if step_time > 0 else 0
                        
                        if step_length > 0:
                            self.stride_lengths.append(step_length)
                            self.velocities.append(velocity)
                            # 性能优化: 增量累加
                            self._stride_sum += step_length
                            self._stride_count += 1
                            self._velocity_sum += velocity
                            self._velocity_count += 1
                            self._update_charts(step_length, velocity, None)
                    
                    self.last_touch_time = timestamp
                    self._last_strike_centroid = cluster.centroid_cm
                    break  # 只处理第一个新增的簇
                    
        elif active_count < self._confirmed_cluster_count:
            # 簇数量减少趋势 → 可能是离地
            self._lift_streak += 1
            self._touch_streak = max(0, self._touch_streak - 1)
            
            if self._lift_streak >= CONFIRM_SAMPLES:
                # 确认离地事件
                self._confirmed_cluster_count = active_count
                self._lift_streak = 0
                self.lift_count += 1
                
                # 计算支撑时间
                target_foot = self._current_foot
                touch_time = self._foot_touch_time.get(target_foot)
                
                if touch_time is not None:
                    support_time = timestamp - touch_time
                    if support_time > 0:
                        if target_foot == "A":
                            self._foot_a_support_times.append(support_time)
                            self._foot_a_support_sum += support_time  # 性能优化: 增量累加
                        else:
                            self._foot_b_support_times.append(support_time)
                            self._foot_b_support_sum += support_time  # 性能优化: 增量累加
        else:
            # 簇数量稳定，重置计数
            self._touch_streak = max(0, self._touch_streak - 1)
            self._lift_streak = max(0, self._lift_streak - 1)
        
        # 更新上一帧状态
        self._prev_cluster_count = active_count
        
        # ===== 性能优化: UI 节流 (10Hz) =====
        current_time = time.perf_counter()
        if current_time - self._last_ui_update >= self._ui_update_interval:
            self._update_gait_display(timestamp, clusters)
            self._last_ui_update = current_time

    def _update_charts(self, h, air_time, contact_time=None):
        """更新柱状图 (与 1data_show.py 中的 _update_charts 完全一致)"""
        if not _PG_AVAILABLE:
            return
        
        # Update Chart 1 (Hop Height or Stride Length)
        self.h_x.append(len(self.h_x) + 1)
        self.h_y.append(h)
        
        # Update Chart 2 (Cadence or Velocity)
        if self.current_mode == "纵跳":
            # 步频公式 (与 1data_show.py 完全一致)
            if contact_time is not None and contact_time > 0:
                cadence = 60.0 / (air_time + contact_time)
            else:
                cadence = 60.0 / air_time if air_time > 0 else 0
            val2 = cadence
        else:
            # air_time 在步态模式中传入的是 velocity
            val2 = air_time
        
        self.cadence_x.append(len(self.cadence_x) + 1)
        self.cadence_y.append(val2)
        
        # 滑动窗口 (与 1data_show.py 完全一致)
        if len(self.h_x) > self.slide_window:
            display_h_x = self.h_x[-self.slide_window:]
            display_h_y = self.h_y[-self.slide_window:]
        else:
            display_h_x = self.h_x
            display_h_y = self.h_y
        
        if len(self.cadence_x) > self.slide_window:
            display_cadence_x = self.cadence_x[-self.slide_window:]
            display_cadence_y = self.cadence_y[-self.slide_window:]
        else:
            display_cadence_x = self.cadence_x
            display_cadence_y = self.cadence_y
        
        self.h_bar.setOpts(x=display_h_x, height=display_h_y, width=0.65, brush=dayu_theme.primary_color)
        self.cadence_bar.setOpts(x=display_cadence_x, height=display_cadence_y, width=0.65, brush='#52c41a')
        
        # X轴范围 (与 1data_show.py 完全一致)
        current_idx = len(self.h_x)
        if current_idx <= self.initial_range:
            self.plot_widget.setXRange(0, self.initial_range, padding=0)
            self.plot_widget_cadence.setXRange(0, self.initial_range, padding=0)
        else:
            x_max = current_idx + 0.5
            x_min = max(0, current_idx - self.slide_window + 0.5)
            self.plot_widget.setXRange(x_min, x_max, padding=0)
            self.plot_widget_cadence.setXRange(x_min, x_max, padding=0)

    def _update_display(self, ev: FootEvent):
        """更新文本显示 (与 1data_show.py 中的 _update_display 完全一致)"""
        if self.current_mode == "纵跳":
            stage = "触地" if ev.kind.lower() == "touch" else "腾空"
            # 离地事件时质心可能为 None，使用上一次触地的质心位置
            if ev.centroid_cm:
                centroid_str = f"{ev.centroid_cm:.2f}cm"
            elif self._last_strike_centroid:
                centroid_str = f"{self._last_strike_centroid:.2f}cm (上次触地)"
            else:
                centroid_str = "--"
            lines = [
                f"模式: 纵跳 (实时)",
                f"当前事件: {stage}",
                f"时刻: {ev.time:.3f}s",
                f"遮挡率: {ev.ratio:.3f}",
                f"质心位置: {centroid_str}",
                "-" * 30,
                f"触地次数: {self.touch_count}",
                f"腾空次数: {self.lift_count}"
            ]
            # 显示腾空时间和跳高 (最新 + 平均)
            if self.air_times:
                latest_air = self.air_times[-1]
                avg_air = sum(self.air_times) / len(self.air_times)
                latest_h = 0.5 * G * (latest_air / 2) ** 2
                avg_h = 0.5 * G * (avg_air / 2) ** 2
                max_h = 0.5 * G * (max(self.air_times) / 2) ** 2
                lines.append(f"最新腾空时间: {latest_air:.3f}s | 平均: {avg_air:.3f}s")
                lines.append(f"最新跳高: {latest_h:.3f}m | 平均: {avg_h:.3f}m | 最大: {max_h:.3f}m")
            # 显示触底时间 (最新 + 平均)
            if self.contact_times:
                latest_contact = self.contact_times[-1]
                avg_contact = sum(self.contact_times) / len(self.contact_times)
                lines.append(f"最新触底时间: {latest_contact:.3f}s | 平均: {avg_contact:.3f}s")
            # 显示步频
            if self.air_times and self.contact_times:
                total_cycle = self.air_times[-1] + self.contact_times[-1]
                cadence = 60.0 / total_cycle if total_cycle > 0 else 0
                lines.append(f"当前步频: {cadence:.1f} steps/min")
        else:
            stage = "触地" if ev.kind.lower() == "touch" else "离地"
            foot_label = self._current_foot if ev.kind.lower() == "touch" else "-"
            # 离地事件时质心可能为 None，使用上一次触地的质心位置
            if ev.centroid_cm:
                centroid_str = f"{ev.centroid_cm:.2f}cm"
            elif self._last_strike_centroid:
                centroid_str = f"{self._last_strike_centroid:.2f}cm (上次触地)"
            else:
                centroid_str = "--"
            lines = [
                f"模式: 步态分析 (实时)",
                f"当前事件: {stage}",
                f"当前脚: Foot {foot_label}" if foot_label != "-" else f"脚: 离地中",
                f"时刻: {ev.time:.3f}s",
                f"质心位置: {centroid_str}",
                "-" * 30,
                f"总步数: {self.touch_count}",
            ]
            # 显示步幅和步速
            if self.stride_lengths:
                avg_stride = sum(self.stride_lengths) / len(self.stride_lengths)
                latest_stride = self.stride_lengths[-1]
                lines.append(f"最新步幅: {latest_stride:.2f} cm")
                lines.append(f"平均步幅: {avg_stride:.2f} cm")
            if self.velocities:
                avg_vel = sum(self.velocities) / len(self.velocities)
                latest_vel = self.velocities[-1]
                lines.append(f"最新步速: {latest_vel:.2f} cm/s")
                lines.append(f"平均步速: {avg_vel:.2f} cm/s")
            # 显示支撑时间
            lines.append("-" * 30)
            if self._foot_a_support_times:
                avg_a = sum(self._foot_a_support_times) / len(self._foot_a_support_times)
                lines.append(f"Foot A 平均支撑时间: {avg_a:.3f}s")
            if self._foot_b_support_times:
                avg_b = sum(self._foot_b_support_times) / len(self._foot_b_support_times)
                lines.append(f"Foot B 平均支撑时间: {avg_b:.3f}s")
        
        self.text_edit_top.setText("\n".join(lines))
        self._apply_line_spacing(self.text_edit_top, 140)

    def _update_gait_display(self, timestamp: float, clusters: list):
        """更新步态分析模式的文本显示 - 性能优化版"""
        # 根据簇数量判断状态
        active_count = len(clusters)
        if active_count == 0:
            status = "腾空"
        elif active_count == 1:
            status = "单脚支撑"
        else:
            status = "双脚支撑"
        
        # 质心位置
        if clusters:
            centroids_str = ", ".join([f"{c.centroid_cm:.1f}cm" for c in clusters])
        else:
            centroids_str = "--"
        
        lines = [
            f"模式: 步态分析 (实时)",
            f"当前状态: {status}",
            f"检测簇数: {active_count}",
            f"时刻: {timestamp:.3f}s",
            f"质心位置: {centroids_str}",
            "-" * 30,
            f"触地次数: {self.touch_count}",
            f"离地次数: {self.lift_count}",
        ]
        # 显示步幅和步速 - 使用增量统计 O(1)
        if self._stride_count > 0:
            avg_stride = self._stride_sum / self._stride_count
            latest_stride = self.stride_lengths[-1] if self.stride_lengths else 0
            lines.append(f"最新步幅: {latest_stride:.2f} cm")
            lines.append(f"平均步幅: {avg_stride:.2f} cm")
        if self._velocity_count > 0:
            avg_vel = self._velocity_sum / self._velocity_count
            latest_vel = self.velocities[-1] if self.velocities else 0
            lines.append(f"最新步速: {latest_vel:.2f} cm/s")
            lines.append(f"平均步速: {avg_vel:.2f} cm/s")
        # 显示支撑时间 - 使用增量统计 O(1)
        lines.append("-" * 30)
        if self._foot_a_support_times:
            avg_a = self._foot_a_support_sum / len(self._foot_a_support_times)
            lines.append(f"Foot A 平均支撑时间: {avg_a:.3f}s")
        if self._foot_b_support_times:
            avg_b = self._foot_b_support_sum / len(self._foot_b_support_times)
            lines.append(f"Foot B 平均支撑时间: {avg_b:.3f}s")
        
        self.text_edit_top.setText("\n".join(lines))
        self._apply_line_spacing(self.text_edit_top, 140)


    def on_pause_clicked(self):
        if not self.paused:
            self.paused = True
            self.btn_pause.setText("继续")
        else:
            self.paused = False
            self.btn_pause.setText("暂停")

    def on_stop_clicked(self):
        self.paused = True
        
        if self.serial_worker:
            try:
                self.serial_worker.stop()
            except Exception:
                pass

        if self.serial_thread:
            try:
                self.serial_thread.quit()
                self.serial_thread.wait(2000)
            except Exception:
                pass
            finally:
                self.serial_thread = None
                self.serial_worker = None

        # 显示汇总 (与 1data_show.py 的 _show_summary 类似)
        self._show_summary()

        self.mode_combo.setEnabled(True)

        try:
            self.btn_pause.setVisible(False)
            self.btn_stop.setVisible(False)
            self.btn_layout.removeWidget(self.btn_pause)
            self.btn_layout.removeWidget(self.btn_stop)
            self.btn_pause.deleteLater()
            self.btn_stop.deleteLater()
        except Exception:
            pass

        self.btn_start.setVisible(True)
        
        # 清空柱状图数据
        if _PG_AVAILABLE:
            self.h_x, self.h_y = [], []
            self.cadence_x, self.cadence_y = [], []
            self.h_bar.setOpts(x=[], height=[])
            self.cadence_bar.setOpts(x=[], height=[])
            self.plot_widget.setXRange(0, self.initial_range, padding=0)
            self.plot_widget_cadence.setXRange(0, self.initial_range, padding=0)

    def _show_summary(self):
        """显示汇总 (与 1data_show.py 的 _show_summary 完全一致)"""
        if self.current_mode == "纵跳":
            lines = ["分析完成！", f"触地次数: {self.touch_count}", f"腾空次数: {self.lift_count}"]
            if self.air_times:
                avg_air = sum(self.air_times) / len(self.air_times)
                max_air = max(self.air_times)
                avg_h = 0.5 * G * (avg_air / 2) ** 2
                max_h = 0.5 * G * (max_air / 2) ** 2
                lines.extend([
                    f"平均腾空时间: {avg_air:.3f}s",
                    f"最大腾空时间: {max_air:.3f}s",
                    f"平均跳高: {avg_h:.3f}m",
                    f"最大跳高: {max_h:.3f}m"
                ])
            if self.contact_times:
                lines.append(f"平均触底时间: {sum(self.contact_times)/len(self.contact_times):.3f}s")
            if self.cycle_times:
                avg_cycle = sum(self.cycle_times) / len(self.cycle_times)
                lines.extend([
                    f"平均步态周期: {avg_cycle:.3f}s",
                    f"步频: {60.0/avg_cycle:.1f} 步/分钟"
                ])
        else:
            lines = ["分析完成！", "-" * 25]
            lines.append(f"总步数: {self.touch_count}")
            # 步幅统计
            if self.stride_lengths:
                avg_stride = sum(self.stride_lengths) / len(self.stride_lengths)
                max_stride = max(self.stride_lengths)
                lines.append(f"平均步幅: {avg_stride:.2f} cm")
                lines.append(f"最大步幅: {max_stride:.2f} cm")
            # 步速统计
            if self.velocities:
                avg_vel = sum(self.velocities) / len(self.velocities)
                max_vel = max(self.velocities)
                lines.append(f"平均步速: {avg_vel:.2f} cm/s")
                lines.append(f"最大步速: {max_vel:.2f} cm/s")
            # 支撑时间统计
            lines.append("-" * 25)
            if self._foot_a_support_times:
                avg_a = sum(self._foot_a_support_times) / len(self._foot_a_support_times)
                lines.append(f"Foot A 平均支撑时间: {avg_a:.3f}s")
                lines.append(f"Foot A 步数: {len(self._foot_a_support_times)}")
            if self._foot_b_support_times:
                avg_b = sum(self._foot_b_support_times) / len(self._foot_b_support_times)
                lines.append(f"Foot B 平均支撑时间: {avg_b:.3f}s")
                lines.append(f"Foot B 步数: {len(self._foot_b_support_times)}")
        
        self.text_edit_top.setText("\n".join(lines))
        self._apply_line_spacing(self.text_edit_top, 140)

    def closeEvent(self, event):
        if self.serial_worker:
            try:
                self.serial_worker.stop()
            except Exception:
                pass
        if self.serial_thread and self.serial_thread.isRunning():
            self.serial_thread.quit()
            self.serial_thread.wait(2000)
        event.accept()


if __name__ == "__main__":
    with application() as app:
        widget = RealTimeGaitWidget()
        dayu_theme.apply(widget)
        # 在 dayu_theme 应用后重新设置 ComboBox 样式以覆盖主题默认的橙色
        widget.mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #3a3a3a;
                color: #e0e0e0;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 14px;
                min-height: 20px;
            }
            QComboBox:hover {
                border-color: #777777;
                background-color: #454545;
            }
            QComboBox:focus {
                border-color: #555555;
                background-color: #3a3a3a;
            }
            QComboBox:on {
                border-color: #555555;
                background-color: #3a3a3a;
            }
            QComboBox QAbstractItemView {
                background-color: #3a3a3a;
                color: #e0e0e0;
                selection-background-color: #4a4a4a;
                border: 1px solid #555555;
            }
        """)
        widget.show()
