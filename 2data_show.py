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

from openpyxl import Workbook

from qtpy import QtWidgets
from qtpy.QtCore import QThread, Qt
from qtpy.QtGui import QTextCursor, QTextBlockFormat
from dayu_widgets.divider import MDivider
from dayu_widgets.push_button import MPushButton
from dayu_widgets.text_edit import MTextEdit
from dayu_widgets import dayu_theme
from dayu_widgets.qt import application

# 导入 UsbWorker 和检测器
try:
    from .usb_worker import UsbWorker
    from .single_leg_hop_npz_parser import SingleFootDetector, LedFrame, FootEvent
    from .gait_npz_parser import ClusterTracker, extract_clusters, LedFrame as GaitLedFrame
    from .camera import Camera
    from .extra_parameter import compute_extra_parameters
except ImportError:
    from usb_worker import UsbWorker
    from single_leg_hop_npz_parser import SingleFootDetector, LedFrame, FootEvent
    from gait_npz_parser import ClusterTracker, extract_clusters, LedFrame as GaitLedFrame
    from camera import Camera
    try:
        from extra_parameter import compute_extra_parameters
    except ImportError:
        def compute_extra_parameters(*args, **kwargs): return {}

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


from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class ContactState:
    contact_id: int
    track_id: Optional[int] = None
    status: str = "candidate"  # candidate | confirmed | lost | lifted
    first_seen_time: float = 0.0
    last_seen_time: float = 0.0
    touch_time: Optional[float] = None
    lift_time: Optional[float] = None
    seen_count: int = 0
    miss_count: int = 0
    centroid_at_touch: Optional[float] = None
    latest_centroid: Optional[float] = None
    centroid_history: List[float] = field(default_factory=list)
    cluster_length_at_touch: Optional[float] = None
    latest_cluster_length: Optional[float] = None
    foot_label: Optional[str] = None   # "A" / "B" / None
    label_confidence: float = 0.0
    step_length: Optional[float] = None
    stride_time: Optional[float] = None
    velocity: Optional[float] = None
    contact_duration: Optional[float] = None
    matched_this_frame: bool = False

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
        self.stride_lengths = []  # 步长 (cm)
        self.velocities = []  # 步速 (cm/s)
        self._foot_a_support_times = []  # Foot A 支撑时间
        self._foot_b_support_times = []  # Foot B 支撑时间
        self._foot_history = {"A": {}, "B": {}}  # 各脚历史数据
        self._prev_cycle_data = {}  # 上一周期数据
        self._latest_extra_metrics = {}  # 最新的额外指标
        self._extra_metrics_history = [] # 历史额外指标

        # 触地驱动的高阶代理指标（仅用于结束汇总，不实时显示）
        self._touch_extra_history = []
        self._last_touch_velocity_for_acc = None
        self._last_touch_time_for_acc = None
        
        # 新版 Contact-Based Tracker 数据
        self._gait_armed = False
        self._no_contact_stable_frames = 0
        self._arm_frames = 10
        self._foot_lift_time = {"A": None, "B": None}
        
        self._next_contact_id = 1
        self._active_contacts = {}       # contact_id -> ContactState
        self._completed_contacts = []    # list[ContactState]
        self._last_confirmed_touch_time = 0.0
        self._last_confirmed_touch_centroid = None
        self._foot_contact_queue = []    # 保存已确认、未离地的 contact_id，按 touch_time 排序
        
        self._contact_confirm_frames = 8      # 连续观测帧数确认触地（降敏：5 -> 8）
        self._contact_lift_miss_frames = 10   # 连续丢失帧数确认离地（降敏：5 -> 10）
        self._min_step_interval = 0.5         # 最小步态间隔限制（降敏：0.3 -> 0.5）
        
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
            r"E:\OptoJump\dayu_demo\Newtongxin\CyUsbInterface\output\CyUsbInterface.dll",
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

        # ---- 数据导出缓存 ----
        self._export_frames = []       # list of list[int], 每帧 96 位
        self._export_timestamps = []   # list of float, 相对时间戳

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
                self.plot_widget.setLabel('left', '步长 (cm)')
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
        self.stride_lengths.clear()
        self.velocities.clear()
        self._foot_a_support_times.clear()
        self._foot_b_support_times.clear()
        self._foot_history = {"A": {}, "B": {}}
        self._prev_cycle_data = {}
        self._latest_extra_metrics = {}
        self._extra_metrics_history.clear()

        # 重置触地驱动高阶代理指标
        self._touch_extra_history.clear()
        self._last_touch_velocity_for_acc = None
        self._last_touch_time_for_acc = None
        
        # 重置 Contact-Based Tracker 状态
        self._gait_armed = False
        self._no_contact_stable_frames = 0
        self._arm_frames = 10
        self._foot_lift_time = {"A": None, "B": None}
        
        self._next_contact_id = 1
        self._active_contacts.clear()
        self._completed_contacts.clear()
        self._foot_contact_queue.clear()
        self._last_confirmed_touch_time = 0.0
        self._last_confirmed_touch_centroid = None
        self._prev_touch_time_for_step = 0.0
        
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

        # 重置导出缓存
        self._export_frames.clear()
        self._export_timestamps.clear()
        
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
        步态分析模式: 使用 ClusterTracker 进行多簇追踪
        
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

        # 记录到导出缓存（保存原始 bits，即反转后的）
        self._export_frames.append(list(bits))
        self._export_timestamps.append(timestamp)
        
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

    def _process_gait_clusters(self, timestamp: float, clusters: list):
        """
        基于 ContactState (对象跟踪) 的步态事件机。
        完全淘汰原先按“屏幕簇总数变动”即刻切脚的脆弱逻辑，改为对独立生命周期的脚印进行 `touch->lift` 闭环管理。
        """
        # Step 1. 获取最新跟踪器识别的所有轨迹视图
        active_tracks = getattr(self.gait_tracker, 'get_active_tracks_view', lambda: [])()

        # [补丁1] Armed 机制：系统需要经历一段无接触期才算准备就绪
        if not active_tracks:
            self._no_contact_stable_frames += 1
        else:
            self._no_contact_stable_frames = 0
            
        if self._no_contact_stable_frames >= self._arm_frames:
            self._gait_armed = True

        # Step 2. 先将所有已记录的 contact 标记为本帧未匹配
        for c in self._active_contacts.values():
            c.matched_this_frame = False

        # Step 3. 用 track_id 优先匹配 contact
        for track in active_tracks:
            contact = self._find_or_create_contact_from_track(track, timestamp)
            self._update_contact_seen(contact, track, timestamp)

        # Step 4. 对本帧未匹配到的 active contact 增加 miss_count
        for contact in self._active_contacts.values():
            if not contact.matched_this_frame and contact.status in ("candidate", "confirmed"):
                contact.miss_count += 1

        # Step 5. candidate -> confirmed（持续存在，触发 touch 事件）
        self._confirm_new_contacts(timestamp)

        # Step 6. confirmed/candidate -> lifted（连续消失，触发 lift 事件）
        self._finalize_lost_contacts(timestamp)

        # Step 7. 性能优化: UI 节流 (10Hz) 更新信息板
        current_time = time.perf_counter()
        if current_time - self._last_ui_update >= getattr(self, '_ui_update_interval', 0.1):
            self._update_gait_display(timestamp, clusters)
            self._last_ui_update = current_time

    # =======================================================
    # 新一代 Contact-Based 状态机支持函数
    # =======================================================

    def _find_or_create_contact_from_track(self, track: dict, timestamp: float) -> ContactState:
        track_id = track["track_id"]
        # 1. 找已有绑定
        for contact in self._active_contacts.values():
            if contact.track_id == track_id and contact.status in ("candidate", "confirmed"):
                return contact

        # 2. 建新 contact
        cid = self._next_contact_id
        self._next_contact_id += 1
        contact = ContactState(
            contact_id=cid,
            track_id=track_id,
            status="candidate",
            first_seen_time=timestamp,
            last_seen_time=timestamp,
            seen_count=0,
            miss_count=0,
        )
        self._active_contacts[cid] = contact
        return contact

    def _update_contact_seen(self, contact: ContactState, track: dict, timestamp: float):
        centroid = float(track["centroid_cm"])
        length_cm = float(track.get("length_cm", 0.0))

        contact.matched_this_frame = True
        contact.last_seen_time = timestamp
        contact.seen_count += 1
        contact.miss_count = 0

        contact.latest_centroid = centroid
        contact.latest_cluster_length = length_cm
        contact.centroid_history.append(centroid)

    def _confirm_new_contacts(self, timestamp: float):
        # [补丁2] 未经历静态期前禁止确认
        if not getattr(self, "_gait_armed", False):
            return

        candidates = [
            c for c in self._active_contacts.values()
            if c.status == "candidate" and c.seen_count >= self._contact_confirm_frames
        ]
        # 按出现时间排序保证触发时序
        candidates.sort(key=lambda c: c.first_seen_time)

        for contact in candidates:
            # [补丁3] 新生窗口限制：低帧率放宽（0.2 -> 0.35）
            contact_age = timestamp - contact.first_seen_time
            if contact_age > 0.35:
                continue

            # [补丁4] 簇长度门槛：提高下限过滤小噪点（8.0 -> 12.0）
            if contact.latest_cluster_length is None or contact.latest_cluster_length < 12.0:
                continue

            # [补丁5] 短窗质心抖动过滤：窗口 3 -> 4，阈值 4.0 -> 2.5
            if len(contact.centroid_history) >= 4:
                recent = contact.centroid_history[-4:]
                jitter = max(recent) - min(recent)
                if jitter > 2.5:
                    continue

            if (timestamp - self._last_confirmed_touch_time) < self._min_step_interval:
                # 间隔过短防抖（可能是被误当成了新脚的噪点）
                continue
            
            contact.status = "confirmed"
            contact.touch_time = contact.first_seen_time
            contact.centroid_at_touch = contact.latest_centroid
            contact.cluster_length_at_touch = contact.latest_cluster_length

            self._handle_touch_event(contact)
            
            self._last_confirmed_touch_time = contact.touch_time
            self._last_confirmed_touch_centroid = contact.centroid_at_touch

    def _handle_touch_event(self, contact: ContactState):
        self.touch_count += 1
        self._foot_contact_queue.append(contact.contact_id)

        # 推断左右脚，不强制轮换
        foot_label, confidence = self._infer_foot_label_on_touch(contact)
        contact.foot_label = foot_label
        contact.label_confidence = confidence

        # 低阶参数：计算绝对步长和瞬间步速
        if self._last_confirmed_touch_centroid is not None and contact.centroid_at_touch is not None:
            step_length = abs(contact.centroid_at_touch - self._last_confirmed_touch_centroid)
            contact.step_length = step_length

            dt = contact.touch_time - self._prev_touch_time_for_step
            if dt > 1e-6:
                contact.stride_time = dt
                contact.velocity = step_length / dt

                # 图表所需的低阶数据
                self.stride_lengths.append(step_length)
                self.velocities.append(contact.velocity)
                self._stride_sum += step_length
                self._stride_count += 1
                self._velocity_sum += contact.velocity
                self._velocity_count += 1
                self._update_charts(step_length, contact.velocity, None)

                # 触地驱动高阶代理指标（仅累计，用于结束汇总）
                touch_extra = {
                    "imbalance_index": None,   # 用相邻步长差分近似
                    "double_support": None,    # 无离地不可严格求，留空
                    "single_support": None,    # 用步间隔近似
                    "acceleration": None,      # 相邻触地速度差分
                }

                if len(self.stride_lengths) >= 2:
                    prev_stride = self.stride_lengths[-2]
                    denom = max((step_length + prev_stride) / 2.0, 1e-6)
                    touch_extra["imbalance_index"] = abs(step_length - prev_stride) / denom * 100.0

                touch_extra["single_support"] = dt

                if self._last_touch_velocity_for_acc is not None and self._last_touch_time_for_acc is not None:
                    dtt = contact.touch_time - self._last_touch_time_for_acc
                    if dtt > 1e-6:
                        touch_extra["acceleration"] = (contact.velocity - self._last_touch_velocity_for_acc) / dtt

                self._last_touch_velocity_for_acc = contact.velocity
                self._last_touch_time_for_acc = contact.touch_time
                self._touch_extra_history.append(touch_extra)

        self._prev_touch_time_for_step = contact.touch_time

        # 仅高置信度进入严格历史供高级运算
        if contact.foot_label in ("A", "B") and contact.label_confidence >= 0.7:
            foot = contact.foot_label
            hist = self._foot_history[foot]
            hist["touch_time"] = contact.touch_time
            hist["centroid"] = contact.centroid_at_touch
            hist["stride_length_cm"] = contact.step_length
            hist["stride_time"] = contact.stride_time
            hist["velocity_cm_s"] = contact.velocity
            hist["is_airborne"] = False
            
            # 回溯空中时间
            prev_lift = self._foot_lift_time.get(foot)
            if prev_lift is not None:
                hist["flight_duration"] = contact.touch_time - prev_lift

    def _infer_foot_label_on_touch(self, new_contact: ContactState):
        # 找出当前地上已有的已确认脚印
        confirmed_on_ground = [
            self._active_contacts[cid]
            for cid in self._foot_contact_queue
            if cid in self._active_contacts and self._active_contacts[cid].status == "confirmed"
        ]
        confirmed_on_ground = [c for c in confirmed_on_ground if c.contact_id != new_contact.contact_id]

        labeled = [c for c in confirmed_on_ground if c.foot_label in ("A", "B") and c.label_confidence >= 0.7]
        if len(labeled) == 1:
            # 双支撑期经典推导：地上有一只明确的A脚，那新下来的肯定是B脚
            other = labeled[0]
            new_label = "B" if other.foot_label == "A" else "A"
            return new_label, 0.8
            
        # 若地上没脚或判断模糊，先留空不强制给标签
        return None, 0.0

    def _finalize_lost_contacts(self, timestamp: float):
        to_lift = []
        for contact in self._active_contacts.values():
            if contact.status in ("candidate", "confirmed"):
                if contact.miss_count >= self._contact_lift_miss_frames:
                    to_lift.append(contact)

        to_lift.sort(key=lambda c: c.touch_time if c.touch_time is not None else c.first_seen_time)
        for contact in to_lift:
            if contact.status == "confirmed":
                self._handle_lift_event(contact, timestamp)
            else:
                # 扔掉从未被确认为真实脚印的噪点 candidate
                self._active_contacts.pop(contact.contact_id, None)

    def _handle_lift_event(self, contact: ContactState, timestamp: float):
        contact.status = "lifted"
        contact.lift_time = contact.last_seen_time
        
        if contact.touch_time is not None and contact.lift_time >= contact.touch_time:
            contact.contact_duration = contact.lift_time - contact.touch_time
            
        self.lift_count += 1

        if contact.contact_id in self._foot_contact_queue:
            self._foot_contact_queue.remove(contact.contact_id)

        # 只有置信度高的标签脚印离地时才触发高阶推演
        if contact.foot_label in ("A", "B") and contact.label_confidence >= 0.7:
            foot = contact.foot_label
            self._foot_lift_time[foot] = contact.lift_time
            hist = self._foot_history[foot]
            hist["lift_time"] = contact.lift_time
            hist["contact_duration"] = contact.contact_duration
            hist["is_airborne"] = True
            
            if foot == "A" and contact.contact_duration:
                self._foot_a_support_times.append(contact.contact_duration)
            elif foot == "B" and contact.contact_duration:
                self._foot_b_support_times.append(contact.contact_duration)
                
            opposite = "B" if foot == "A" else "A"
            try:
                extra = compute_extra_parameters(
                    cycle_data_main=dict(hist),
                    cycle_data_opposite=dict(self._foot_history[opposite]),
                    prev_cycle_data=self._prev_cycle_data.get(foot)
                )
                self._latest_extra_metrics = extra
                self._extra_metrics_history.append(extra)
                self._prev_cycle_data[foot] = dict(hist)
            except Exception as e:
                print(f"[Extra Metrics] Calc Error: {e}")

        self._completed_contacts.append(contact)
        self._active_contacts.pop(contact.contact_id, None)

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
            # 显示步长和步速
            if self.stride_lengths:
                avg_stride = sum(self.stride_lengths) / len(self.stride_lengths)
                latest_stride = self.stride_lengths[-1]
                lines.append(f"最新步长: {latest_stride:.2f} cm")
                lines.append(f"平均步长: {avg_stride:.2f} cm")
            if self.velocities:
                avg_vel = sum(self.velocities) / len(self.velocities)
                latest_vel = self.velocities[-1]
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
            
        # ======== 新增：扩展计算步态运动学参数 ========
        if getattr(self, '_latest_extra_metrics', None):
            em = self._latest_extra_metrics
            lines.append("-" * 30)
            lines.append("[ 高阶运动学特征 ]")
            if em.get("alpha_deg") is not None: 
                lines.append(f"起跳切线角: {em['alpha_deg']:.1f}°")
            if em.get("imbalance_index") is not None: 
                lines.append(f"左右脚不平稳度: {em['imbalance_index']:.1f}%")
            if em.get("double_support") is not None: 
                lines.append(f"双支撑期耗时: {em['double_support']:.3f}s")
            if em.get("single_support") is not None: 
                lines.append(f"单支撑期耗时: {em['single_support']:.3f}s")
            if em.get("acceleration") is not None: 
                lines.append(f"前后加速度: {em['acceleration']:.2f} cm/s²")
        
        self.text_edit_top.setText("\n".join(lines))
        self._apply_line_spacing(self.text_edit_top, 140)

    def _update_gait_display(self, timestamp: float, clusters: list):
        """更新步态分析模式的文本显示 - 兼容无标签对象跟踪"""
        # 根据真实确立的物理接触面判断状态
        active_count = len(self._foot_contact_queue)
        if active_count == 0:
            status = "腾空 / 离地"
        elif active_count == 1:
            status = "单脚支撑"
        else:
            status = f"多支撑 ({active_count}脚)"
        
        # 活跃脚印的位置
        active_centroids = [
            f"{self._active_contacts[cid].latest_centroid:.1f}cm"
            for cid in self._foot_contact_queue if cid in self._active_contacts
        ]
        centroids_str = ", ".join(active_centroids) if active_centroids else "--"
        
        lines = [
            f"模式: 步态分析 (Object Tracking)",
            f"步态阶段: {status}",
            f"原始光斑数: {len(clusters)} 簇",
            f"时间: {timestamp:.3f}s",
            f"脚印坐标: {centroids_str}",
            "-" * 30,
            f"累计触地: {self.touch_count} 次",
            f"累计离地: {self.lift_count} 次",
        ]
        # 显示步长和步速 - 使用增量统计 O(1)
        if self._stride_count > 0:
            avg_stride = self._stride_sum / self._stride_count
            latest_stride = self.stride_lengths[-1] if self.stride_lengths else 0
            lines.append(f"最新步长: {latest_stride:.2f} cm")
            lines.append(f"平均步长: {avg_stride:.2f} cm")
        if self._velocity_count > 0:
            avg_vel = self._velocity_sum / self._velocity_count
            latest_vel = self.velocities[-1] if self.velocities else 0
            lines.append(f"最新步速: {latest_vel:.2f} cm/s")
            lines.append(f"平均步速: {avg_vel:.2f} cm/s")
            
        # 显示支撑时间
        lines.append("-" * 30)
        has_support_data = False
        if self._foot_a_support_times:
            avg_a = sum(self._foot_a_support_times) / len(self._foot_a_support_times)
            lines.append(f"Foot A 平均支撑时间: {avg_a:.3f}s")
            has_support_data = True
        if self._foot_b_support_times:
            avg_b = sum(self._foot_b_support_times) / len(self._foot_b_support_times)
            lines.append(f"Foot B 平均支撑时间: {avg_b:.3f}s")
            has_support_data = True
            
        if not has_support_data and getattr(self, "lift_count", 0) > 0:
             lines.append(f"(仍在积累有标签数据的支撑期...)")
        
        # ======== 高阶运动学特征 ========
        if getattr(self, '_latest_extra_metrics', None):
            em = self._latest_extra_metrics
            lines.append("-" * 30)
            lines.append("[ 高阶运动学特征 ]")
            if em.get("imbalance_index") is not None: 
                lines.append(f"左右脚不平稳度: {em['imbalance_index']:.1f}%")
            if em.get("double_support") is not None: 
                lines.append(f"双支撑期耗时: {em['double_support']:.3f}s")
            if em.get("single_support") is not None: 
                lines.append(f"单支撑期耗时: {em['single_support']:.3f}s")
            if em.get("acceleration") is not None: 
                lines.append(f"前后加速度: {em['acceleration']:.2f} cm/s²")
        
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

        # 导出数据
        self._save_export()

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
            # 步长统计
            if self.stride_lengths:
                avg_stride = sum(self.stride_lengths) / len(self.stride_lengths)
                max_stride = max(self.stride_lengths)
                lines.append(f"平均步长: {avg_stride:.2f} cm")
                lines.append(f"最大步长: {max_stride:.2f} cm")
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
            # 高阶指标汇总
            if getattr(self, '_extra_metrics_history', None):
                lines.append("-" * 25)
                lines.append("[ 高阶运动学汇总 ]")
                # 对每个指标键收集非 None 值并求均值
                metric_keys = [
                    ("imbalance_index", "平均不平衡指数", "%", 1),
                    ("double_support", "平均双支撑期", "s", 3),
                    ("single_support", "平均单支撑期", "s", 3),
                    ("acceleration", "平均加速度", "cm/s²", 2),
                ]
                for key, label, unit, decimals in metric_keys:
                    vals = [m[key] for m in self._extra_metrics_history if m.get(key) is not None]
                    if vals:
                        avg = sum(vals) / len(vals)
                        lines.append(f"{label}: {avg:.{decimals}f}{unit}")
            
            # 触地驱动高阶指标汇总（仅结束显示）
            if self._touch_extra_history:
                lines.append("-" * 25)
                # lines.append("[ 高阶运动学汇总（触地驱动） ]")
                metric_keys = [
                    ("imbalance_index", "平均不平衡指数", "%", 1),
                    ("single_support", "平均步间隔", "s", 3),
                    ("acceleration", "平均加速度", "cm/s²", 2),
                ]
                for key, label, unit, decimals in metric_keys:
                    vals = [m[key] for m in self._touch_extra_history if m.get(key) is not None]
                    if vals:
                        avg = sum(vals) / len(vals)
                        lines.append(f"{label}: {avg:.{decimals}f}{unit}")

                # 新增：平均步频（基于触地步间隔）
                step_intervals = [
                    m.get("single_support")
                    for m in self._touch_extra_history
                    if m.get("single_support") is not None and m.get("single_support") > 1e-6
                ]
                if step_intervals:
                    avg_step_interval = sum(step_intervals) / len(step_intervals)
                    cadence = 60.0 / avg_step_interval
                    lines.append(f"平均步频: {cadence:.1f} 步/分钟")

        self.text_edit_top.setText("\n".join(lines))
        self._apply_line_spacing(self.text_edit_top, 140)

    def _save_export(self):
        """将缓存的 LED 位图帧导出为 Excel 文件。"""
        if not self._export_frames:
            return

        # 弹出确认对话框
        reply = QtWidgets.QMessageBox.question(
            self,
            "导出数据",
            f"本次采集共 {len(self._export_frames)} 帧数据，是否保存？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        # 固定保存路径
        save_dir = r"E:\OptoJump\dayu_demo\demo\data"
        os.makedirs(save_dir, exist_ok=True)
        filename = time.strftime("led_frames_%Y%m%d_%H%M%S.xlsx")
        path = os.path.join(save_dir, filename)

        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "LED Frames"
            # 表头：timestamp, hex_string
            ws.append(["timestamp", "hex_string"])
            # 逐行写入：将 96 位列表还原为 12 字节十六进制字符串（LSB-first）
            for ts, bits in zip(self._export_timestamps, self._export_frames):
                hex_bytes = []
                for i in range(0, 96, 8):
                    byte_val = 0
                    for j in range(8):
                        byte_val |= (bits[i + j] << j)
                    hex_bytes.append(byte_val)
                hex_str = " ".join(f"{b:02x}" for b in hex_bytes)
                ws.append([ts, hex_str])
            wb.save(path)
            QtWidgets.QMessageBox.information(
                self, "导出成功", f"数据已保存至：\n{path}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "导出失败", f"保存文件失败：{e}")

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
