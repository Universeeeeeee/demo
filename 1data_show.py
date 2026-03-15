"""
用于从npz文件中解析步态参数，并展现在前端界面中
"""
from qtpy import QtWidgets
from qtpy.QtCore import QTimer
from qtpy.QtGui import QTextCursor, QTextBlockFormat
from dayu_widgets.divider import MDivider
from dayu_widgets.push_button import MPushButton
from dayu_widgets.text_edit import MTextEdit
from dayu_widgets.combo_box import MComboBox
from dayu_widgets import dayu_theme
from dayu_widgets.qt import application
import importlib

# 导入单腿跳跃分析器
try:
    from .single_leg_hop_npz_parser import NpzFrameReader, SingleFootDetector, FootEvent
    from .gait_npz_parser import analyze_walking_gait, NpzFrameReader as GaitNpzReader, GaitEvent
except ImportError:
    from single_leg_hop_npz_parser import NpzFrameReader, SingleFootDetector, FootEvent
    from gait_npz_parser import analyze_walking_gait, NpzFrameReader as GaitNpzReader, GaitEvent

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

DEFAULT_NPZ_PATH = r"E:\OptoJump\dayu_demo\single_leg_hop.npz"
GAIT_NPZ_PATH = r"E:\OptoJump\dayu_demo\gait_capture_20251223.npz"
G = 9.81


class DataShowWidget(QtWidgets.QWidget):
    def __init__(self, parent=None, npz_path=DEFAULT_NPZ_PATH):
        super().__init__(parent)
        self.npz_path = npz_path
        self.paused = False
        self.frames = []
        self.replay_timer = None
        self.detector = None
        self.all_events = []
        self.current_event_idx = 0
        self.touch_count = 0
        self.lift_count = 0
        self.last_touch_time = None
        self.last_lift_time = None
        self.cycle_times = []
        self.air_times = []
        self.contact_times = []
        self.cadence_data = []  # 步频数据
        
        # Gait specific data
        self.current_mode = "Single Leg Hop" # "Single Leg Hop" or "Gait Analysis"
        self.gait_events = []
        self.gait_cycles = []
        self.gait_cycle_index = 0  # Index for sequential cycle matching
        self.gait_summary = {}
        self.gait_direction = "unknown"
        self.stride_lengths = []
        self.velocities = []

        self.mass = 70.0
        self.initial_range = 10  # 初始X轴范围
        self.slide_window = 15   # 滑动窗口：显示最近15个数据
        self._init_ui()
        self.setMinimumSize(1000, 600)
        self.resize(1000, 600)

    def _init_ui(self):
        self.main_lay = QtWidgets.QHBoxLayout()
        left_layout = QtWidgets.QVBoxLayout()
        
        left_layout.addWidget(MDivider("模式选择"))
        self.mode_combo = MComboBox()
        self.mode_combo.addItems(["Single Leg Hop", "Gait Analysis"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)
        left_layout.addWidget(self.mode_combo)

        left_layout.addWidget(MDivider("分析详情"))
        self.text_edit_top = MTextEdit(self)
        self.text_edit_top.setReadOnly(True)
        self.text_edit_top.setMinimumSize(200, 300)
        self.text_edit_top.setObjectName("data_display_edit")
        self.text_edit_top.setStyleSheet("QTextEdit#data_display_edit { font-size: 14pt; }")
        left_layout.addWidget(self.text_edit_top, 1)
        left_layout.addWidget(MDivider("操作"))

        self.btn_container = QtWidgets.QWidget()
        self.btn_container.setMinimumHeight(60)
        self.btn_layout = QtWidgets.QHBoxLayout(self.btn_container)
        self.btn_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_start = MPushButton("开始分析").primary()
        self.btn_start.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.btn_start.setStyleSheet("QPushButton { font-size: 20px; }")
        self.btn_start.setMinimumHeight(60)
        self.btn_start.clicked.connect(self.on_start_clicked)
        self.btn_layout.addWidget(self.btn_start)
        left_layout.addWidget(self.btn_container, 0)

        right_layout = QtWidgets.QVBoxLayout()
        right_layout.addWidget(MDivider("数据可视化"))

        if _PG_AVAILABLE:
            # 跳高柱状图
            self.plot_widget = pg.PlotWidget()
            self.plot_widget.setBackground(dayu_theme.background_in_color)
            self.plot_widget.showGrid(x=True, y=True, alpha=0.2)
            self.plot_widget.setLabel('left', '跳高 h (m)')
            self.plot_widget.setLabel('bottom', '跳跃次数')
            self.plot_widget.enableAutoRange(axis='y')
            self.plot_widget.setXRange(0, 10, padding=0)  # 初始X轴范围[0, 10]
            self.h_x, self.h_y = [], []
            self.h_bar = pg.BarGraphItem(x=[], height=[], width=0.65, brush=dayu_theme.primary_color)
            self.plot_widget.addItem(self.h_bar)
            right_layout.addWidget(self.plot_widget, 1)

            # 步频柱状图
            self.plot_widget_cadence = pg.PlotWidget()
            self.plot_widget_cadence.setBackground(dayu_theme.background_in_color)
            self.plot_widget_cadence.showGrid(x=True, y=True, alpha=0.2)
            self.plot_widget_cadence.setLabel('left', '步频 (steps/min)')
            self.plot_widget_cadence.setLabel('bottom', '跳跃次数')
            self.plot_widget_cadence.enableAutoRange(axis='y')
            self.plot_widget_cadence.setXRange(0, 10, padding=0)  # 初始X轴范围[0, 10]
            self.cadence_x, self.cadence_y = [], []
            self.cadence_bar = pg.BarGraphItem(x=[], height=[], width=0.65, brush='#52c41a')
            self.plot_widget_cadence.addItem(self.cadence_bar)
            right_layout.addWidget(self.plot_widget_cadence, 1)
        else:
            placeholder = QtWidgets.QLabel("未安装 pyqtgraph")
            right_layout.addWidget(placeholder)

        self.main_lay.addLayout(left_layout, 1)
        self.main_lay.addLayout(right_layout, 2)
        self.setLayout(self.main_lay)

    def _apply_line_spacing(self, edit, percent=150):
        cursor = edit.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)
        fmt = QTextBlockFormat()
        fmt.setLineHeight(float(percent), 1)
        cursor.mergeBlockFormat(fmt)
        cursor.endEditBlock()

    def on_start_clicked(self):
        self.paused = False
        self.btn_start.setVisible(False)
        self.btn_pause = MPushButton("暂停")
        self.btn_pause.setMinimumHeight(60)
        self.btn_stop = MPushButton("结束")
        self.btn_stop.setMinimumHeight(60)
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.btn_layout.addWidget(self.btn_pause)
        self.btn_layout.addWidget(self.btn_stop)
        self._load_and_analyze()

    def on_mode_changed(self, text):
        self.current_mode = text
        if text == "Single Leg Hop":
            self.npz_path = DEFAULT_NPZ_PATH
            if _PG_AVAILABLE:
                 self.plot_widget.setLabel('left', '跳高 h (m)')
                 self.plot_widget.setLabel('bottom', '跳跃次数')
                 self.plot_widget_cadence.setLabel('left', '步频 (steps/min)')
                 self.plot_widget_cadence.setLabel('bottom', '跳跃次数')
        else:
            self.npz_path = GAIT_NPZ_PATH
            if _PG_AVAILABLE:
                 self.plot_widget.setLabel('left', '步幅 (cm)')
                 self.plot_widget.setLabel('bottom', '步数')
                 self.plot_widget_cadence.setLabel('left', '步速 (cm/s)')
                 self.plot_widget_cadence.setLabel('bottom', '步数')
        
        # Reset charts
        if _PG_AVAILABLE:
            self.h_x, self.h_y = [], []
            self.cadence_x, self.cadence_y = [], []
            # Enforce styles to match Single Leg Hop (Color & Width)
            self.h_bar.setOpts(x=[], height=[], width=0.65, brush=dayu_theme.primary_color)
            self.cadence_bar.setOpts(x=[], height=[], width=0.65, brush='#52c41a')

    def _load_and_analyze(self):
        try:
            if self.current_mode == "Single Leg Hop":
                self._analyze_single_leg_hop()
            else:
                self._analyze_gait()
        except Exception as e:
            self.text_edit_top.setText(f"加载数据失败: {e}")
            import traceback
            traceback.print_exc()

    def _analyze_single_leg_hop(self):
        reader = NpzFrameReader(self.npz_path)
        reader.load()
        meta = reader.get_meta()
        duration = meta.get("duration_s", 1.0)
        self.frames = list(reader.iter_frames_protocol())
        if not self.frames:
            self.text_edit_top.setText("未解析到有效帧数据")
            return
        
        # Normalize timestamps
        if len(self.frames) > 1:
            max_ts = max(f.timestamp for f in self.frames)
            min_ts = min(f.timestamp for f in self.frames)
            ts_range = max_ts - min_ts if max_ts > min_ts else 1.0
            for f in self.frames:
                f.timestamp = (f.timestamp - min_ts) / ts_range * duration

        self.detector = SingleFootDetector(touch_ratio_threshold=0.12, lift_ratio_threshold=0.05, confirm_samples=2)
        self.all_events = []
        last_ev = None
        for frame in self.frames:
            for ev in self.detector.consume(frame):
                if last_ev is not None:
                    self.all_events.append(last_ev)
                last_ev = ev
        if last_ev is not None and last_ev.kind.lower() == "touch":
            self.all_events.append(last_ev)

        self._reset_analysis_state()
        
        sample_rate = len(self.frames) / duration if duration > 0 else 0
        info = f"模式: 单腿跳跃\n数据文件: {self.npz_path}\n总帧数: {len(self.frames)}\n录制时长: {duration:.2f}s\n采样率: {sample_rate:.1f} Hz\n检测到 {len(self.all_events)} 个步态事件\n开始回放分析..."
        self.text_edit_top.setText(info)
        self._start_replay()

    def _analyze_gait(self):
        reader = GaitNpzReader(self.npz_path)
        reader.load()
        meta = reader.get_meta()
        duration = meta.get("duration_s", 1.0)
        
        # Use simple simple iteration for frames first, assuming protocol parser might fail or we just need frames
        # Actually adapt to use whatever analyze_walking_gait expects (LedFrame list)
        frames = list(reader.iter_frames_protocol())
        if not frames: 
             self.text_edit_top.setText("未解析到有效帧数据")
             return

        tracks, events, cycles, summary, direction = analyze_walking_gait(
            frames, duration, 
            min_cluster_length=10, 
            t_min_ms=50, 
            max_shift_led=6
        )

        self.all_events = events  # Reuse all_events for replay loop
        # Sort cycles by strike_time for sequential matching during replay
        self.gait_cycles = sorted(cycles, key=lambda c: c.strike_time)
        self.gait_summary = summary
        self.gait_direction = direction
        
        self._reset_analysis_state()
        self.stride_lengths = []
        self.velocities = []

        # Reset charts for incremental update during playback
        if _PG_AVAILABLE:
            self.h_x, self.h_y = [], []
            self.cadence_x, self.cadence_y = [], []
            self.h_bar.setOpts(x=[], height=[], width=0.65, brush=dayu_theme.primary_color)
            self.cadence_bar.setOpts(x=[], height=[], width=0.65, brush='#52c41a')
            
            # Reset X-axis to initial range
            self.plot_widget.setXRange(0, self.initial_range, padding=0)
            self.plot_widget_cadence.setXRange(0, self.initial_range, padding=0)

        sample_rate = len(frames) / duration if duration > 0 else 0
        info = f"模式: 步态分析\n数据文件: {self.npz_path}\n录制时长: {duration:.2f}s\n采样率: {sample_rate:.1f} Hz\n方向: {direction}\n检测到 {len(self.all_events)} 个步态事件\n开始回放分析..."
        self.text_edit_top.setText(info)
        self._start_replay()

    def _reset_analysis_state(self):
        self.touch_count = 0
        self.lift_count = 0
        self.last_touch_time = None
        self.last_lift_time = None
        self._last_strike_centroid = None  # For gait mode step_length calculation
        self.cycle_times = []
        self.air_times = []
        self.contact_times = []
        self.gait_cycle_index = 0  # Reset cycle index for replay
        self.cadence_data = []
        self.current_event_idx = 0
        if _PG_AVAILABLE:
            self.h_x, self.h_y = [], []
            self.cadence_x, self.cadence_y = [], []
            self.h_bar.setOpts(x=[], height=[])
            self.cadence_bar.setOpts(x=[], height=[])
            self.plot_widget.setXRange(0, self.initial_range, padding=0)
            self.plot_widget_cadence.setXRange(0, self.initial_range, padding=0)

    def _start_replay(self):
        self._apply_line_spacing(self.text_edit_top, 140)
        self.replay_timer = QTimer(self)
        self.replay_timer.timeout.connect(self._replay_next_event)
        self.replay_timer.start(500)

    # REMOVED OLD _load_and_analyze content to be replaced by above methods
    def _dummy_placeholder(self):
         pass 

    def _replay_next_event(self):
        if self.paused:
            return
        if self.current_event_idx >= len(self.all_events):
            self.replay_timer.stop()
            self._show_summary()
            return
        ev = self.all_events[self.current_event_idx]
        self.current_event_idx += 1
        # Handle different event types
        if self.current_mode == "Single Leg Hop":
            self._process_hop_event(ev)
        else:
            self._process_gait_event(ev)
        
    def _process_hop_event(self, ev):
        if ev.kind.lower() == "touch":
            self.touch_count += 1
            if self.last_lift_time is not None:
                air_time = ev.time - self.last_lift_time
                if air_time > 0:
                    self.air_times.append(air_time)
                    h = 0.5 * G * (air_time / 2) ** 2
                    # 获取最新的contact_time用于计算步频
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

    def _process_gait_event(self, ev):
        # Process gait events and update charts synchronously with replay
        # Use step_length (distance between consecutive strikes) instead of stride_length
        # because stride_length requires multiple tracks per foot which may not be available
        
        if ev.event_type == "foot_strike":
            self.touch_count += 1
            
            # Calculate step_length from consecutive foot strikes
            if self.last_touch_time is not None and self._last_strike_centroid is not None:
                # Step length: distance between this strike and the previous one
                step_length = abs(ev.centroid_cm - self._last_strike_centroid)
                # Step time: time between strikes  
                step_time = ev.time - self.last_touch_time
                # Velocity: step_length / step_time
                velocity = step_length / step_time if step_time > 0 else 0
                
                # Update charts with step_length and velocity
                self._update_charts(step_length, velocity, None)
            
            # Store current strike info for next calculation
            self.last_touch_time = ev.time
            self._last_strike_centroid = ev.centroid_cm
            
        elif ev.event_type == "toe_off":
            self.lift_count += 1
            
        self._update_display(ev)

    def _update_charts(self, h, air_time, contact_time=None):
        """更新柱状图，支持滑动窗口和Y轴自适应"""
        if not _PG_AVAILABLE:
            return
        
        # Update Chart 1 (Hop Height or Stride Length)
        self.h_x.append(len(self.h_x) + 1)
        self.h_y.append(h)
        
        # Update Chart 2 (Cadence or Velocity)
        if self.current_mode == "Single Leg Hop":
            # 计算步频: cadence = 60 / (air_time + contact_time)
            if contact_time is not None and contact_time > 0:
                cadence = 60.0 / (air_time + contact_time)
            else:
                cadence = 60.0 / air_time if air_time > 0 else 0
            val2 = cadence
        else:
             # air_time passed as val2 (velocity) for gait mode in _process_gait_event
             val2 = air_time # Rename vars locally if confusing, but keeping sig same
        
        self.cadence_x.append(len(self.cadence_x) + 1)
        self.cadence_y.append(val2)
        
        # 应用滑动窗口显示数据
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
        
        # 更新柱状图
        self.h_bar.setOpts(x=display_h_x, height=display_h_y, width=0.65, brush=dayu_theme.primary_color)
        self.cadence_bar.setOpts(x=display_cadence_x, height=display_cadence_y, width=0.65, brush='#52c41a')
        
        # 设置X轴范围：阶段一(填充期)固定[0,10]，阶段二(滚动期)滑动窗口
        current_idx = len(self.h_x)
        if current_idx <= self.initial_range:
            # 阶段一：数据点<10时，X轴固定在[0, 10]
            self.plot_widget.setXRange(0, self.initial_range, padding=0)
            self.plot_widget_cadence.setXRange(0, self.initial_range, padding=0)
        else:
            # 阶段二：数据点>10时，X轴开始滑动，显示最近slide_window个数据
            x_max = current_idx + 0.5
            x_min = max(0, current_idx - self.slide_window + 0.5)
            self.plot_widget.setXRange(x_min, x_max, padding=0)
            self.plot_widget_cadence.setXRange(x_min, x_max, padding=0)

    def _update_display(self, ev):
        if self.current_mode == "Single Leg Hop":
            stage = "触地" if ev.kind.lower() == "touch" else "腾空"
            centroid_str = f"{ev.centroid_cm:.2f}cm" if ev.centroid_cm else "N/A"
            lines = [f"模式: 单腿跳跃", f"当前事件: {stage}", f"时刻: {ev.time:.3f}s", f"遮挡率: {ev.ratio:.3f}", f"质心位置: {centroid_str}", "-" * 30, f"触地次数: {self.touch_count}", f"腾空次数: {self.lift_count}"]
            if self.air_times:
                latest_air = self.air_times[-1]
                latest_h = 0.5 * G * (latest_air / 2) ** 2
                lines.append(f"最新腾空时间: {latest_air:.3f}s")
                lines.append(f"最新跳高: {latest_h:.3f}m")
            if self.contact_times:
                lines.append(f"最新触底时间: {self.contact_times[-1]:.3f}s")
        else:
            # Gait Mode
            stage = "触地 (Strike)" if ev.event_type == "foot_strike" else "离地 (Toe-off)"
            foot = f"Foot {ev.foot_label}" if ev.foot_label else "Unknown Foot"
            lines = [f"模式: 步态分析", f"当前事件: {stage}", f"脚: {foot}", f"时刻: {ev.time:.3f}s", f"质心位置: {ev.centroid_cm:.2f}cm", "-" * 30]
            
            # Find cycle info if available just to display latest stats
            if self.gait_cycles:
                 # Find last completed cycle or just show summary so far
                 pass
            
            lines.append(f"步数 (Strikes): {self.touch_count}")
        
        self.text_edit_top.setText("\n".join(lines))
        self._apply_line_spacing(self.text_edit_top, 140)

    def _show_summary(self):
        if self.current_mode == "Single Leg Hop":
            lines = [ "分析完成！ ", f"触地次数: {self.touch_count}", f"腾空次数: {self.lift_count}"]
            if self.air_times:
                avg_air = sum(self.air_times) / len(self.air_times)
                max_air = max(self.air_times)
                avg_h = 0.5 * G * (avg_air / 2) ** 2
                max_h = 0.5 * G * (max_air / 2) ** 2
                lines.extend([f"平均腾空时间: {avg_air:.3f}s", f"最大腾空时间: {max_air:.3f}s", f"平均跳高: {avg_h:.3f}m", f"最大跳高: {max_h:.3f}m"])
            if self.contact_times:
                lines.append(f"平均触底时间: {sum(self.contact_times)/len(self.contact_times):.3f}s")
            if self.cycle_times:
                avg_cycle = sum(self.cycle_times) / len(self.cycle_times)
                lines.extend([f"平均步态周期: {avg_cycle:.3f}s", f"步频: {60.0/avg_cycle:.1f} 步/分钟"])
        else:
            s = self.gait_summary
            lines = ["分析完成！", "-"*20]
            lines.append(f"总步数 (FootA): {s.get('foot_a_count', 0)}")
            lines.append(f"总步数 (FootB): {s.get('foot_b_count', 0)}")
            if "avg_velocity_m_s" in s:
                lines.append(f"平均步速: {s['avg_velocity_m_s']:.2f} m/s")
            if "avg_stride_length_cm" in s:
                lines.append(f"平均步幅: {s['avg_stride_length_cm']:.2f} cm")
            if "cadence_steps_per_min" in s:
                 lines.append(f"步频: {s['cadence_steps_per_min']:.1f} 步/分钟")
            if "avg_support_time_s" in s:
                 lines.append(f"平均支撑时间: {s['avg_support_time_s']:.3f} s")
            
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
        if self.replay_timer:
            self.replay_timer.stop()
        self.text_edit_top.setText("")
        if _PG_AVAILABLE:
            self.h_x, self.h_y = [], []
            self.cadence_x, self.cadence_y = [], []
            self.h_bar.setOpts(x=[], height=[], width=0.65)
            self.cadence_bar.setOpts(x=[], height=[], width=0.65)
            # 重置X轴为初始范围[0, 10]
            self.plot_widget.setXRange(0, self.initial_range, padding=0)
            self.plot_widget_cadence.setXRange(0, self.initial_range, padding=0)
        self.btn_pause.setVisible(False)
        self.btn_stop.setVisible(False)
        self.btn_layout.removeWidget(self.btn_pause)
        self.btn_layout.removeWidget(self.btn_stop)
        self.btn_pause.deleteLater()
        self.btn_stop.deleteLater()
        self.btn_start.setVisible(True)


if __name__ == "__main__":
    with application() as app:
        widget = DataShowWidget()
        dayu_theme.apply(widget)
        widget.show()
