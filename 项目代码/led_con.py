
from qtpy import QtWidgets
from qtpy.QtCore import QThread, QObject, Signal, Qt, QTimer
from dayu_widgets.divider import MDivider
from dayu_widgets.push_button import MPushButton
from dayu_widgets.text_edit import MTextEdit
from dayu_widgets.qt import application
from dayu_widgets import dayu_theme
import threading
import time
import sys
import os
from collections import deque

from receive import CyUsbInterfaceDevice, E_DATA_REPORT


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


# 新增：USB 硬件数据 Worker（基于 receive.CyUsbInterfaceDevice）
class UsbWorker(QObject):
    data_received = Signal(str)  # 文本日志（HEX）
    led_bits_signal = Signal(list)  # 96 位 LED 位图

    def __init__(self, dll_path=None, vid=0x04B4, pid=0x1004, timeout_ms=200, chunk_size=2048):
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
        # 节流设置（默认日志 200ms、LED 50ms，可用环境变量覆盖）
        self.log_interval = max(0.0, float(os.getenv("DAYU_LOG_INTERVAL_MS", "200")) / 1000.0)
        self.led_interval = max(0.0, float(os.getenv("DAYU_LED_INTERVAL_MS", "30")) / 1000.0)
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
        self._flush_timer.setInterval(max(10, int(interval_s * 1000)))
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
    """基于 Dayu 风格的界面，用于展示 start_test 产生的数据帧（左侧文本），右侧为图表占位（不绘图）。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        # USB 设备配置（可通过环境变量覆盖）
        self.dll_path = os.getenv(
            "DAYU_DLL",
            "CyUsbInterface.dll",
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
        self.timeout_ms = _parse_int_env("DAYU_TIMEOUT", 200)
        self.chunk_size = _parse_int_env("DAYU_CHUNK", 2048)
        self.serial_thread = None
        self.serial_worker = None
        self.paused = False

        self._init_ui()
        self.setMinimumSize(1000, 600)
        # 帧计数/缓存（每10帧刷新一次UI）
        self._frame_counter = 0
        self._last_hex = ""
        self._last_led_bits = None
        # 最近5帧文本滚动缓存
        self._hex_log = deque(maxlen=10)
    
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

        # 左侧：数据帧展示
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.addWidget(MDivider("数据展示"))
        self.text_edit = MTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setObjectName("data_display_edit")
        self.text_edit.setStyleSheet("QTextEdit#data_display_edit { font-size: 14pt; }")
        left_layout.addWidget(self.text_edit, 1)

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

        # 右侧：LED 面板
        right_layout = QtWidgets.QVBoxLayout()
        right_layout.addWidget(MDivider("LED 面板 (96)"))
        self.led_panel = LEDPanel(rows=8, cols=12, parent=self)
        right_layout.addWidget(self.led_panel, 1)

        self.main_lay.addLayout(left_layout, 1)
        self.main_lay.addLayout(right_layout, 2)
        self.setLayout(self.main_lay)

    def on_start_clicked(self):
        self.paused = False
        self.btn_start.setVisible(False)

        # 创建 暂停 / 结束 按钮
        self.btn_pause = MPushButton("暂停")
        self.btn_pause.setMinimumHeight(60)
        self.btn_stop = MPushButton("结束")
        self.btn_stop.setMinimumHeight(60)
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.btn_layout.addWidget(self.btn_pause)
        self.btn_layout.addWidget(self.btn_stop)

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
    # 接收数据并缓存（仅在未暂停时），每 10 帧刷新一次
        self.serial_worker.data_received.connect(self._on_hex_received)
        self.serial_worker.led_bits_signal.connect(self._on_led_bits_received)
        # 当线程结束时清理 worker
        self.serial_thread.finished.connect(self.serial_worker.deleteLater)
        self.serial_thread.start()

    def _on_hex_received(self, hex_str: str):
        if self.paused:
            return
        self._last_hex = hex_str
        # 记录到滚动日志
        try:
            self._hex_log.append(hex_str)
        except Exception:
            pass
        # 即使还没有 LED 帧，也主动刷新文本，方便看到状态/错误
        try:
            self.text_edit.setText("\n".join(self._hex_log))
        except Exception:
            pass

    def _on_led_bits_received(self, bits: list):
        if self.paused:
            return
        self._last_led_bits = bits
        self._frame_counter += 1
        # 方案A：首帧立刷，其后每10帧刷新一次
        if self._frame_counter == 1 or (self._frame_counter % 10 == 0):
            # 刷新文本为最近5帧（滚动显示）
            try:
                self.text_edit.setText("\n".join(self._hex_log))
            except Exception:
                pass
            # 刷新LED面板
            if self._last_led_bits is not None:
                self.led_panel.set_leds(self._last_led_bits)

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

        # 清空文本
        self.text_edit.setText("")
        # 清空 LED 面板
        try:
            self.led_panel.clear()
        except Exception:
            pass

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


if __name__ == '__main__':
    with application() as app:
        widget = SerialDataWidget()
        dayu_theme.apply(widget)
        widget.show()
        sys.exit(app.exec_())