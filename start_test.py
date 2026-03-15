
from qtpy import QtWidgets
from qtpy.QtCore import QThread, QObject, Signal, Qt, QTimer
from dayu_widgets.divider import MDivider
from dayu_widgets.push_button import MPushButton
from dayu_widgets.text_edit import MTextEdit
from dayu_widgets.label import MLabel
from dayu_widgets.qt import application
from dayu_widgets import dayu_theme
import threading
import time
import sys
import os
import math
from collections import deque, OrderedDict
from typing import List

from receive import CyUsbInterfaceDevice, E_DATA_REPORT
from Gait_cal import GaitAnalyzer, LedSample, GaitCycle, GaitEvent


class LEDPanel(QtWidgets.QWidget):
    """简单的 8x12 LED 面板：绿色=亮，灰色=灭。"""
    def __init__(self, rows=8, cols=12, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.cols = cols
        self._cells = []  # list[list[QLabel]]
        lay = QtWidgets.QGridLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setHorizontalSpacing(6)
        lay.setVerticalSpacing(6)
        size = 18
        for r in range(rows):
            row_cells = []
            for c in range(cols):
                lab = QtWidgets.QLabel()
                lab.setFixedSize(size, size)
                lab.setStyleSheet(self._style_off())
                lab.setAlignment(Qt.AlignCenter)
                lay.addWidget(lab, r, c)
                row_cells.append(lab)
            self._cells.append(row_cells)

    def _style_on(self):
        return (
            "background-color: #2ecc71; border: 1px solid #1b874a; border-radius: 3px;"
        )

    def _style_off(self):
        return (
            "background-color: #4b4b4b; border: 1px solid #2e2e2e; border-radius: 3px;"
        )

    def clear(self):
        for r in range(self.rows):
            for c in range(self.cols):
                self._cells[r][c].setStyleSheet(self._style_off())

    def set_leds(self, bits):
        """bits: 长度<=96，按 LSB→MSB，索引 i 映射到 (row=i//12, col=i%12) 水平排列。

        1 表示 LED 亮（绿色），0 表示熄灭/遮挡。
        """
        # 保护：只取前 96 位
        n = min(96, len(bits))
        # 先全部置灭
        self.clear()
        for i in range(n):
            if bits[i]:
                row = i // 12  # 0..7（行优先，水平连续）
                col = i % 12   # 0..11
                if 0 <= row < self.rows and 0 <= col < self.cols:
                    self._cells[row][col].setStyleSheet(self._style_on())


class GaitResultsWidget(QtWidgets.QWidget):
    """显示步态分析结果：事件列表和周期参数。"""
    def __init__(self, parent=None, gait_analyzer=None):
        super().__init__(parent)
        self.gait_analyzer = gait_analyzer
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建文本展示区
        self.text_edit = MTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setObjectName("gait_results_edit")
        self.text_edit.setStyleSheet("QTextEdit#gait_results_edit { font-family: 'Consolas', monospace; font-size: 11pt; }")
        layout.addWidget(self.text_edit)

        self.pending_label = MLabel("")
        self.pending_label.setAlignment(Qt.AlignRight)
        self.pending_label.setStyleSheet("color: #8c8c8c; font-size: 10pt;")
        layout.addWidget(self.pending_label)
        
        # 累积的分析次数
        self._analysis_count = 0
        self._cycle_counter = 0
        self._last_touch_timestamp = 0.0  # 用于去重：记录上一次已显示的周期触底时间
        self._processed_touch_times = set()  # 用于去重：记录所有已处理的触底时间戳（精确到0.01秒）
        self._pending_cycles = OrderedDict()
        
    def display_results(self, result, mode="walk", append=True):
        """显示步态分析结果，并避免重复输出表头。"""
        if not append:
            self.clear()

        if not result.cycles:
            self._update_pending_hint()
            return

        resolved_cycles: List[GaitCycle] = []
        new_complete_cycles: List[GaitCycle] = []

        for cycle in result.cycles:
            touch_time = cycle.touch_event.time
            # 使用更严格的去重：检查是否已经处理过这个触底时间（精确到0.01秒）
            touch_time_key = round(touch_time, 2)  # 精确到0.01秒，避免浮点误差
            if touch_time_key in self._processed_touch_times:
                continue  # 已处理过，跳过
            
            # 同时检查时间戳是否小于等于上次显示的时间（额外保护）
            if touch_time <= self._last_touch_timestamp + 0.01:
                continue

            resolved = self._resolve_pending_cycle(cycle.touch_event)
            if resolved:
                resolved_cycles.append(resolved)
                # 标记已处理
                resolved_touch_key = round(resolved.touch_event.time, 2)
                self._processed_touch_times.add(resolved_touch_key)

            if cycle.next_touch_event is None:
                key = round(touch_time, 5)
                if key not in self._pending_cycles:
                    self._pending_cycles[key] = cycle
                continue

            self._pending_cycles.pop(round(touch_time, 5), None)
            new_complete_cycles.append(cycle)
            # 标记已处理
            self._processed_touch_times.add(touch_time_key)

        pending_count = len(self._pending_cycles)
        ready_cycles = resolved_cycles + new_complete_cycles

        if not ready_cycles:
            self._update_pending_hint(pending_count)
            return

        # 更新最后显示的时间戳
        self._last_touch_timestamp = ready_cycles[-1].touch_event.time

        self._analysis_count += 1
        timestamp = time.strftime("%H:%M:%S")
        mode_cn = "纵跳模式" if mode == "jump" else "步行模式"

        batch_lines = [
            "——" * 30,
            f"分析批次 #{self._analysis_count} · {timestamp} · {mode_cn}",
            f"采样率 {result.sampling_rate_hz:.1f} Hz | 新增有效周期 {len(ready_cycles)} 个",
        ]
        for cycle in ready_cycles:
            self._cycle_counter += 1
            batch_lines.extend(self._format_cycle_block(cycle, mode, self._cycle_counter))

        new_block = "\n".join(batch_lines).rstrip()
        if not new_block:
            return

        existing = self.text_edit.toPlainText()
        if existing:
            combined = "\n".join([existing, new_block])
        else:
            combined = new_block
        self.text_edit.setPlainText(combined)

        scrollbar = self.text_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        self._update_pending_hint(pending_count)
    
    def clear(self):
        """清空显示。"""
        self.text_edit.clear()
        self.pending_label.clear()
        self._analysis_count = 0
        self._cycle_counter = 0
        self._last_touch_timestamp = 0.0
        self._processed_touch_times.clear()
        self._pending_cycles.clear()

    def _format_cycle_block(self, cycle, mode: str, index: int) -> List[str]:
        lines = [f"周期 {index:02d}"]
        touch_line = f"  触底时间：{cycle.touch_event.time:.3f}s"
        status_line = (
            "  状态：已闭合"
            if cycle.next_touch_event is not None
            else "  状态：等待下一次触地（数据暂不完整）"
        )
        lines.extend([touch_line, status_line])

        if mode == "jump":
            if cycle.flight_duration is not None:
                flight_line = f"  腾空时间：{cycle.flight_duration:.3f}s"
                height_cm = (9.8 * (cycle.flight_duration ** 2) / 8.0) * 100.0
                height_line = f"  腾空高度：{height_cm:.2f}cm"
            else:
                flight_line = "  腾空时间：无效(过短)"
                height_line = "  腾空高度：--"
            lines.extend([flight_line, height_line])
        else:
            if cycle.lift_event:
                lift_line = f"  离地时间：{cycle.lift_event.time:.3f}s"
            else:
                lift_line = "  离地时间：--"
            if cycle.stride_cm is not None:
                stride_line = f"  步幅：{cycle.stride_cm:.2f}cm"
                # 添加质心信息用于调试
                if (
                    cycle.touch_event.centroid is not None
                    and cycle.next_touch_event is not None
                    and cycle.next_touch_event.centroid is not None
                ):
                    c1 = cycle.touch_event.centroid
                    c2 = cycle.next_touch_event.centroid
                    centroid_info = f"  [质心X: {c1:.2f} → {c2:.2f}]"
                    lines.append(centroid_info)
            else:
                stride_line = "  步幅：无效(计算失败)"
                # 如果步幅无效，显示质心信息帮助诊断
                if (
                    cycle.touch_event.centroid is not None
                    and cycle.next_touch_event is not None
                    and cycle.next_touch_event.centroid is not None
                ):
                    c1 = cycle.touch_event.centroid
                    c2 = cycle.next_touch_event.centroid
                    dx = c2 - c1
                    raw_distance = abs(dx)
                    centroid_info = (
                        f"  [原始位移: {raw_distance:.2f}cm, 质心X: {c1:.2f} → {c2:.2f}]"
                    )
                    lines.append(centroid_info)
            lines.extend([lift_line, stride_line])

        lines.append("")
        return lines

    def _update_pending_hint(self, pending_count=None):
        if pending_count is None:
            pending_count = len(self._pending_cycles)
        if pending_count:
            self.pending_label.setText(
                f"检测到 {pending_count} 个周期尚未闭合，等待下一次触地…"
            )
        else:
            self.pending_label.clear()

    def _resolve_pending_cycle(self, next_touch_event: GaitEvent):
        if not self._pending_cycles:
            return None
        oldest_key = next(iter(self._pending_cycles))
        pending_cycle = self._pending_cycles[oldest_key]
        if pending_cycle.lift_event is None:
            self._pending_cycles.pop(oldest_key, None)
            self._update_pending_hint()
            return None
        pending_cycle = self._pending_cycles.pop(oldest_key)
        pending_cycle.next_touch_event = next_touch_event
        if pending_cycle.lift_event is not None:
            pending_cycle.flight_duration = max(
                next_touch_event.time - pending_cycle.lift_event.time,
                0.0,
            )
        if (
            pending_cycle.touch_event.centroid is not None
            and next_touch_event.centroid is not None
        ):
            # 使用 GaitAnalyzer 的方法计算并验证步幅
            if self.gait_analyzer is not None:
                pending_cycle.stride_cm = self.gait_analyzer.compute_stride(
                    pending_cycle.touch_event,
                    next_touch_event,
                )
            else:
                # 降级方案：如果没有 gait_analyzer，使用简单的距离计算
                dx = next_touch_event.centroid - pending_cycle.touch_event.centroid
                pending_cycle.stride_cm = abs(dx)
        return pending_cycle



# 新增：USB 硬件数据 Worker（基于 receive.CyUsbInterfaceDevice）
class UsbWorker(QObject):
    data_received = Signal(str)  # 文本日志（HEX）
    led_bits_signal = Signal(list)  # 96 位 LED 位图

    def __init__(self, dll_path=None, vid=0x04B4, pid=0x1004, timeout_ms=30, chunk_size=512):
        super().__init__()
        self.dll_path = dll_path
        self.vid = int(vid)
        self.pid = int(pid)
        self.timeout_ms = int(timeout_ms)
        self.chunk_size = int(chunk_size)
        self.dev = None
        self._stop = threading.Event()
        # 分包缓存：frameIdx -> { 'packs': {packIdx: bytes}, 'packNum': int }
        self._frames = {}
        # 节流设置（默认日志 100ms、LED 由目标采样率推导，可用环境变量覆盖）
        self.log_interval = max(0.0, float(os.getenv("DAYU_LOG_INTERVAL_MS", "100")) / 1000.0)
        target_rate = max(1.0, float(os.getenv("DAYU_TARGET_RATE_HZ", "200")))
        led_interval_override = os.getenv("DAYU_LED_INTERVAL_MS")
        if led_interval_override:
            self.led_interval = max(0.0, float(led_interval_override) / 1000.0)
        else:
            self.led_interval = 1.0 / target_rate
        self.target_rate_hz = target_rate
        self.debug_raw = os.getenv("DAYU_DEBUG_USB_RAW", "0") == "1"
        self._last_log_ts = 0.0
        self._last_led_ts = 0.0
        self._pending_hex = None
        self._pending_bits = None
        self._flush_timer = None

    # --- 工具 ---
    def _emit(self, msg: str):
        try:
            self.data_received.emit(msg)
        except Exception:
            print(msg)

    def _bytes_to_bits(self, payload: bytes):
        # 按 LSB→MSB 展开，最多取前 12 字节 = 96 位
        bits = []
        for b in payload[:12]:
            for i in range(8):
                bits.append((b >> i) & 0x1)
        return bits[:96]

    def _extract_payload(self, subpack) -> bytes:
        # 适配多种可能字段名
        cand_names = ["body", "payload", "data", "buffer", "buf"]
        buf = None
        for name in cand_names:
            if hasattr(subpack, name):
                try:
                    val = getattr(subpack, name)
                    if val is not None:
                        buf = val
                        break
                except Exception:
                    pass
        if buf is None:
            return b""
        try:
            raw = bytes(buf)
        except Exception:
            try:
                raw = bytes(bytearray(buf))
            except Exception:
                raw = b""
        # 若存在 bufferLen，进行安全截断
        try:
            blen = int(getattr(subpack, "bufferLen"))
            if 0 < blen <= len(raw):
                raw = raw[:blen]
        except Exception:
            pass
        return raw

    def _queue_update(self, hex_text=None, bits=None):
        if hex_text:
            self._pending_hex = hex_text
        if bits is not None:
            self._pending_bits = bits
        self._maybe_flush()

    def _maybe_flush(self, force=False):
        now = time.perf_counter()
        if self._pending_hex and (force or self.log_interval == 0.0 or now - self._last_log_ts >= self.log_interval):
            msg = self._pending_hex
            self._pending_hex = None
            self._last_log_ts = now
            try:
                self.data_received.emit(msg)
            except Exception:
                pass
        if self._pending_bits is not None and (force or self.led_interval == 0.0 or now - self._last_led_ts >= self.led_interval):
            bits_to_emit = self._pending_bits
            self._pending_bits = None
            self._last_led_ts = now
            try:
                self.led_bits_signal.emit(bits_to_emit)
            except Exception:
                pass

    def _on_flush_timer(self):
        self._maybe_flush()

    def _ensure_timer(self):
        if self._flush_timer is not None:
            return
        candidates = [val for val in (self.log_interval, self.led_interval) if val > 0.0]
        if not candidates:
            return
        interval_s = min(candidates)
        self._flush_timer = QTimer()
        self._flush_timer.setInterval(max(1, int(interval_s * 1000)))
        self._flush_timer.timeout.connect(self._on_flush_timer)
        self._flush_timer.start()

    def _flush_led_if_ready(self, frameIdx: int):
        node = self._frames.get(frameIdx)
        if not node:
            return
        packs = node.get("packs", {})
        packNum = node.get("packNum", 0)
        if packNum <= 0 or len(packs) < packNum:
            return
        # 合并：兼容 packIdx 从 1 或 0 开始
        payload = bytearray()
        ordered = False
        try:
            for i in range(1, packNum + 1):
                payload.extend(packs[i])
            ordered = True
        except Exception:
            pass
        if not ordered:
            try:
                for i in range(0, packNum):
                    payload.extend(packs[i])
            except Exception:
                pass
        if len(payload) >= 12:
            body12 = bytes(payload[:12])
            bits = self._bytes_to_bits(body12)
            self._queue_update(hex_text=body12.hex(" "), bits=bits)
        # 清理该帧缓存
        self._frames.pop(frameIdx, None)

    # --- 设备回调 ---
    def _on_bytes(self, data: bytes):
        if not self.debug_raw:
            return
        try:
            head = data[:16].hex(" ")
            self._queue_update(hex_text=f"RAW len={len(data)} head={head}")
        except Exception:
            pass

    def _on_frame(self, frame_type, ack, subpack, status):
        # 仅处理数据上报帧
        if E_DATA_REPORT is not None and frame_type != E_DATA_REPORT:
            return
        if not subpack:
            return
        # 读取分包标识
        try:
            frameIdx = int(getattr(subpack, "frameIdx"))
        except Exception:
            frameIdx = 0
        try:
            packNum = int(getattr(subpack, "packNum"))
        except Exception:
            packNum = 1
        try:
            packIdx = int(getattr(subpack, "packIdx"))
        except Exception:
            packIdx = 1
        payload = self._extract_payload(subpack)
        if not payload:
            return
        # 单包直接处理
        if packNum <= 1 and len(payload) >= 12:
            body12 = payload[:12]
            bits = self._bytes_to_bits(body12)
            self._queue_update(hex_text=body12.hex(" "), bits=bits)
            return
        # 多包：缓存并尝试合并
        node = self._frames.setdefault(frameIdx, {"packs": {}, "packNum": packNum})
        node["packs"][packIdx] = bytes(payload)
        node["packNum"] = max(node.get("packNum", packNum), packNum)
        self._flush_led_if_ready(frameIdx)

    # --- 生命周期 ---
    def start(self):
        if CyUsbInterfaceDevice is None:
            self._emit("无法导入 receive.CyUsbInterfaceDevice，请检查 demo/receive.py 与 DLL 可用性。")
            return
        try:
            self.dev = CyUsbInterfaceDevice(self.dll_path)
        except Exception as e:
            self._emit(f"加载 DLL 失败: {e}")
            return
        if not self.dev.open(self.vid, self.pid):
            self._emit(f"打开设备失败: VID=0x{self.vid:04X} PID=0x{self.pid:04X}")
            return
        self._emit(f"设备已打开 VID=0x{self.vid:04X} PID=0x{self.pid:04X}")
        self._ensure_timer()
        try:
            try:
                self.dev.dll.set_timeout(self.timeout_ms)
            except Exception:
                pass
            self.dev.start_capture()
            self.dev.set_on_bytes(self._on_bytes)
            self.dev.set_on_frame(self._on_frame)
            ret = self.dev.start_auto_read(self.chunk_size)
            if ret != 0:
                self._emit(f"start_auto_read 失败: {ret}")
        except Exception as e:
            self._emit(f"启动读取失败: {e}")

    def stop(self):
        self._stop.set()
        if self._flush_timer is not None:
            try:
                self._flush_timer.stop()
            except Exception:
                pass
            self._flush_timer.deleteLater()
            self._flush_timer = None
        # 尝试最后一次刷新
        self._maybe_flush(force=True)
        if self.dev:
            try:
                self.dev.set_on_bytes(None)
            except Exception:
                pass
            try:
                self.dev.set_on_frame(None)
            except Exception:
                pass
            try:
                self.dev.stop_auto_read()
            except Exception:
                pass
            try:
                self.dev.stop_capture()
            except Exception:
                pass
            try:
                self.dev.close()
            except Exception:
                pass
            self.dev = None


class SerialDataWidget(QtWidgets.QWidget):
    """基于 Dayu 风格的界面，展示步态分析结果。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        # USB 设备配置（可通过环境变量覆盖）
        self.dll_path = os.getenv(
            "DAYU_DLL",
            r"E:\OptoJump\dayu_demo\Newtongxin\CyUsbInterface\output\CyUsbInterface.dll",
        )
        def _parse_int_env(name, default):
            v = os.getenv(name)
            if not v:
                return default
            try:
                return int(v, 0)  # 支持十六进制如 0x04B4
            except Exception:
                return default
        self.vid = _parse_int_env("DAYU_VID", 0x04B4)
        self.pid = _parse_int_env("DAYU_PID", 0x1004)
        self.timeout_ms = _parse_int_env("DAYU_TIMEOUT", 30)
        self.chunk_size = _parse_int_env("DAYU_CHUNK", 256)
        self.serial_thread = None
        self.serial_worker = None
        self.paused = False

        # 测试模式："jump" 纵跳 或 "walk" 步行
        self.test_mode = "walk"
        
        # 步态分析器
        self.gait_analyzer = GaitAnalyzer()
        self._apply_config_overrides_from_env()

        # 运行时调节能力
        self._invert_led_bits = self._parse_bool_env("DAYU_INVERT_BITS", False)
        self._analysis_interval = max(0.5, float(os.getenv("DAYU_ANALYSIS_INTERVAL", "2.0")))
        self._max_history_seconds = max(0.0, float(os.getenv("DAYU_HISTORY_SECONDS", "12")))
        self._min_samples_for_analysis = max(2, int(os.getenv("DAYU_MIN_SAMPLES", "5")))

        # 采样缓存：收集足够帧数后才进行分析
        self._led_samples = deque()
        self._sample_start_time = None
        self._last_analysis_time = None

        # 采样率监控
        self._sample_tick_times = deque(maxlen=400)

        self._init_ui()
        self.setMinimumSize(1000, 600)
    
    def closeEvent(self, event):
        """窗口关闭时，确保线程正确停止"""
        if self.serial_worker:
            try:
                self.serial_worker.stop()
            except Exception:
                pass
        if self.serial_thread and self.serial_thread.isRunning():
            self.serial_thread.quit()
            self.serial_thread.wait(2000)
        event.accept()

    def _init_ui(self):
        self.main_lay = QtWidgets.QHBoxLayout()

        # 左侧：步态参数展示
        left_layout = QtWidgets.QVBoxLayout()
        
        # 左上角：模式切换按钮
        mode_layout = QtWidgets.QHBoxLayout()
        mode_layout.setContentsMargins(0, 0, 0, 10)
        
        self.btn_jump_mode = MPushButton("纵跳模式")
        self.btn_walk_mode = MPushButton("步行模式").primary()
        self.btn_jump_mode.setMinimumHeight(40)
        self.btn_walk_mode.setMinimumHeight(40)
        self.btn_jump_mode.clicked.connect(self.on_jump_mode_clicked)
        self.btn_walk_mode.clicked.connect(self.on_walk_mode_clicked)
        
        mode_layout.addWidget(self.btn_jump_mode)
        mode_layout.addWidget(self.btn_walk_mode)
        mode_layout.addStretch()
        
        left_layout.addLayout(mode_layout)

        self.sample_rate_label = QtWidgets.QLabel("当前采样率：-- Hz (目标 200)")
        self.sample_rate_label.setStyleSheet("color: #2ecc71; font-size: 11pt;")
        left_layout.addWidget(self.sample_rate_label)
        left_layout.addWidget(MDivider("参数分析"))
        
        self.gait_results = GaitResultsWidget(self, gait_analyzer=self.gait_analyzer)
        left_layout.addWidget(self.gait_results, 1)

        # 按钮区
        self.btn_container = QtWidgets.QWidget()
        self.btn_container.setMinimumHeight(60)
        self.btn_layout = QtWidgets.QHBoxLayout(self.btn_container)
        self.btn_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_start = MPushButton("开始测试").primary()
        self.btn_start.setMinimumHeight(60)
        self.btn_start.clicked.connect(self.on_start_clicked)
        self.btn_layout.addWidget(self.btn_start)

        left_layout.addWidget(self.btn_container, 0)

        # 右侧：空白区域（预留）
        right_layout = QtWidgets.QVBoxLayout()
        right_layout.addWidget(MDivider(""))
        # 添加一个空白占位组件
        placeholder = QtWidgets.QWidget()
        right_layout.addWidget(placeholder, 1)

        self.main_lay.addLayout(left_layout, 1)
        self.main_lay.addLayout(right_layout, 2)
        self.setLayout(self.main_lay)

    def on_start_clicked(self):
        self.paused = False
        self.btn_start.setVisible(False)
        
        # 确保界面和状态被重置
        self.gait_results.clear()
        
        # 测试开始后禁用模式切换按钮
        self.btn_jump_mode.setEnabled(False)
        self.btn_walk_mode.setEnabled(False)

        # 创建 暂停 / 结束 按钮
        self.btn_pause = MPushButton("暂停")
        self.btn_pause.setMinimumHeight(60)
        self.btn_stop = MPushButton("结束")
        self.btn_stop.setMinimumHeight(60)
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.btn_layout.addWidget(self.btn_pause)
        self.btn_layout.addWidget(self.btn_stop)

        # 重置采样缓存
        self._led_samples.clear()
        self._sample_start_time = time.perf_counter()
        self._last_analysis_time = None
        self._sample_tick_times.clear()
        self._update_sampling_rate_label()

        # 启用 USB 硬件 worker
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
        # 接收 LED 数据并进行步态分析
        self.serial_worker.led_bits_signal.connect(self._on_led_bits_received)
        # 当线程结束时清理 worker
        self.serial_thread.finished.connect(self.serial_worker.deleteLater)
        self.serial_thread.start()

    def on_jump_mode_clicked(self):
        """切换到纵跳模式。"""
        if self.serial_thread and self.serial_thread.isRunning():
            # 测试进行中不允许切换模式
            return
        self.test_mode = "jump"
        self.btn_jump_mode.set_dayu_type(MPushButton.PrimaryType)
        self.btn_walk_mode.set_dayu_type(MPushButton.DefaultType)
    
    def on_walk_mode_clicked(self):
        """切换到步行模式。"""
        if self.serial_thread and self.serial_thread.isRunning():
            # 测试进行中不允许切换模式
            return
        self.test_mode = "walk"
        self.btn_walk_mode.set_dayu_type(MPushButton.PrimaryType)
        self.btn_jump_mode.set_dayu_type(MPushButton.DefaultType)

    def _on_led_bits_received(self, bits: list):
        """接收 LED 位图并累积样本，定期进行步态分析。"""
        if self.paused:
            return

        # 对原始位图进行可选翻转
        if self._invert_led_bits:
            bits = [0 if b else 1 for b in bits]

        current_time = time.perf_counter()
        self._sample_tick_times.append(current_time)
        self._update_sampling_rate_label()
        if self._sample_start_time is None:
            self._sample_start_time = current_time

        timestamp = current_time - self._sample_start_time
        sample = LedSample(timestamp=timestamp, bits=bits)
        self._led_samples.append(sample)
        self._prune_history(timestamp)

        elapsed_since_last = (
            current_time - self._last_analysis_time
            if self._last_analysis_time is not None
            else current_time - self._sample_start_time
        )

        if (
            elapsed_since_last >= self._analysis_interval
            and len(self._led_samples) >= self._min_samples_for_analysis
        ):
            window_duration = self._led_samples[-1].timestamp - self._led_samples[0].timestamp
            if window_duration >= 0.2:
                self._perform_gait_analysis(analysis_time=current_time)

    def _perform_gait_analysis(self, analysis_time=None):
        """执行步态分析并更新显示。"""
        if len(self._led_samples) < 2:
            return
        if analysis_time is None:
            analysis_time = time.perf_counter()
        samples_snapshot = list(self._led_samples)
        try:
            result = self.gait_analyzer.process(samples_snapshot)
            # 使用追加模式显示结果，保留之前的所有分析结果
            self.gait_results.display_results(result, mode=self.test_mode, append=True)
        except Exception as e:
            # 显示错误信息（也追加）
            error_msg = (
                f"\n[错误] 步态分析出错: {str(e)}\n样本数: {len(samples_snapshot)}\n"
            )
            current_text = self.gait_results.text_edit.toPlainText()
            self.gait_results.text_edit.setText(current_text + error_msg)
        finally:
            self._last_analysis_time = analysis_time

    def _prune_history(self, latest_timestamp: float) -> None:
        """按照最大保留时长裁剪历史样本。"""
        if self._max_history_seconds <= 0:
            return
        cutoff = latest_timestamp - self._max_history_seconds
        while self._led_samples and self._led_samples[0].timestamp < cutoff:
            self._led_samples.popleft()

    @staticmethod
    def _parse_bool_env(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        value = value.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
        return default

    def _apply_config_overrides_from_env(self) -> None:
        cfg = self.gait_analyzer.config

        def _update(attr: str, raw_value):
            if attr == "confirm_samples":
                value = max(1, int(raw_value))
            else:
                value = float(raw_value) if isinstance(raw_value, str) else raw_value
            if attr == "confirm_samples":
                cfg.confirm_samples = value
                self.gait_analyzer.confirm_samples = value
            else:
                setattr(cfg, attr, value)
                setattr(self.gait_analyzer, attr, value)

        if self._parse_bool_env("DAYU_LOWER_THRESH", False):
            _update("touch_ratio_threshold", min(cfg.touch_ratio_threshold, 0.30))
            _update("lift_ratio_threshold", min(cfg.lift_ratio_threshold, 0.12))

        touch_env = os.getenv("DAYU_TOUCH_THRESHOLD")
        if touch_env:
            try:
                clamp = max(0.05, min(0.95, float(touch_env)))
                _update("touch_ratio_threshold", clamp)
            except ValueError:
                pass

        lift_env = os.getenv("DAYU_LIFT_THRESHOLD")
        if lift_env:
            try:
                clamp = max(0.01, min(0.5, float(lift_env)))
                _update("lift_ratio_threshold", clamp)
            except ValueError:
                pass

        confirm_env = os.getenv("DAYU_CONFIRM_SAMPLES")
        if confirm_env:
            try:
                _update("confirm_samples", max(1, int(confirm_env)))
            except ValueError:
                pass

        min_contact_env = os.getenv("DAYU_MIN_CONTACT_MS")
        if min_contact_env:
            try:
                _update("min_contact_duration_ms", max(20.0, float(min_contact_env)))
            except ValueError:
                pass

        min_flight_env = os.getenv("DAYU_MIN_FLIGHT_MS")
        if min_flight_env:
            try:
                _update("min_flight_duration_ms", max(20.0, float(min_flight_env)))
            except ValueError:
                pass

        min_cycle_env = os.getenv("DAYU_MIN_CYCLE_MS")
        if min_cycle_env:
            try:
                _update("min_cycle_interval_ms", max(50.0, float(min_cycle_env)))
            except ValueError:
                pass

    def on_pause_clicked(self):
        if not self.paused:
            self.paused = True
            self.btn_pause.setText("继续")
        else:
            self.paused = False
            self.btn_pause.setText("暂停")

    def on_stop_clicked(self):
        self.paused = True
        # 停止 worker（先设置停止事件）
        if self.serial_worker:
            try:
                self.serial_worker.stop()
            except Exception:
                pass
        
        # 等待线程完全结束后再清理
        if self.serial_thread:
            try:
                self.serial_thread.quit()
                self.serial_thread.wait(2000)  # 等待最多2秒
            except Exception:
                pass
            finally:
                # 清理线程引用
                self.serial_thread = None
                self.serial_worker = None

        # 点击"结束"后清空显示
        self.gait_results.clear()
        
        # 清空采样缓存
        self._led_samples.clear()
        self._sample_start_time = None
        self._last_analysis_time = None
        self._sample_tick_times.clear()
        self._update_sampling_rate_label()
        
        # 恢复模式切换按钮
        self.btn_jump_mode.setEnabled(True)
        self.btn_walk_mode.setEnabled(True)

        # 移除暂停和结束按钮
        try:
            self.btn_pause.setVisible(False)
            self.btn_stop.setVisible(False)
            self.btn_layout.removeWidget(self.btn_pause)
            self.btn_layout.removeWidget(self.btn_stop)
            self.btn_pause.deleteLater()
            self.btn_stop.deleteLater()
        except Exception:
            pass

        # 恢复开始按钮
        self.btn_start.setVisible(True)

    def _update_sampling_rate_label(self):
        if not hasattr(self, "sample_rate_label"):
            return
        if len(self._sample_tick_times) < 2:
            self.sample_rate_label.setText("当前采样率：-- Hz (目标 200)")
            return
        duration = self._sample_tick_times[-1] - self._sample_tick_times[0]
        if duration <= 0:
            self.sample_rate_label.setText("当前采样率：-- Hz (目标 200)")
            return
        rate = (len(self._sample_tick_times) - 1) / duration
        self.sample_rate_label.setText(f"当前采样率：{rate:.1f} Hz (目标 200)")


if __name__ == '__main__':
    with application() as app:
        widget = SerialDataWidget()
        dayu_theme.apply(widget)
        widget.show()
        sys.exit(app.exec_())