'''脚长检测后端逻辑'''
from __future__ import annotations

import os
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

from qtpy.QtCore import QObject, QThread, Signal, Slot

from led_con import UsbWorker

__all__ = ["calculate_foot_length", "FootLengthBackend"]


def calculate_foot_length(
    bits: List[int],
    baseline_bits: Optional[List[int]],
    spacing_cm: float = 1.04,
) -> Optional[float]:
    """根据遮挡的连续 LED 数量估算脚长（厘米）。"""
    if not bits:
        return None

    length = min(len(bits), 96)
    if baseline_bits is None:
        baseline_bits = bits

    occluded_indices: List[int] = []
    baseline_length = min(len(baseline_bits), 96)
    limit = min(length, baseline_length)
    for i in range(limit):
        if baseline_bits[i] == 0 and bits[i] == 1:
            occluded_indices.append(i)

    if not occluded_indices:
        return None

    occluded_indices.sort()
    max_len = 1
    current_len = 1
    for i in range(1, len(occluded_indices)):
        if occluded_indices[i] == occluded_indices[i - 1] + 1:
            current_len += 1
        else:
            if current_len > max_len:
                max_len = current_len
            current_len = 1
    if current_len > max_len:
        max_len = current_len

    foot_length = max_len * spacing_cm
    if 15.0 <= foot_length <= 35.0:
        return foot_length
    return None


class FootLengthBackend(QObject):
    """脚长检测业务逻辑，负责与硬件交互及状态管理。"""

    led_bits_signal = Signal(list)
    status_changed = Signal(str)
    result_text_changed = Signal(str)
    state_changed = Signal(dict)
    detection_completed = Signal(float, dict)
    error_occurred = Signal(str)

    def __init__(self, parent: Optional[QObject] = None, spacing_cm: float = 1.04) -> None:
        super().__init__(parent)
        self.spacing_cm = spacing_cm

        # USB 配置（支持环境变量覆盖）
        self.dll_path = os.getenv(
            "DAYU_DLL",
            r"E:\OptoJump\dayu_demo\Newtongxin\CyUsbInterface\output\CyUsbInterface.dll",
        )

        def _parse_int_env(name: str, default: int) -> int:
            value = os.getenv(name)
            if not value:
                return default
            try:
                return int(value, 0)
            except Exception:
                return default

        self.vid = _parse_int_env("DAYU_VID", 0x04B4)
        self.pid = _parse_int_env("DAYU_PID", 0x1004)
        self.timeout_ms = _parse_int_env("DAYU_TIMEOUT", 200)
        self.chunk_size = _parse_int_env("DAYU_CHUNK", 2048)

        self.serial_thread: Optional[QThread] = None
        self.serial_worker: Optional[UsbWorker] = None

        # 检测运行时状态
        self.is_detecting = False
        self.detection_phase = "idle"
        self.foot_detected = False
        self.result_foot_length: Optional[float] = None

        # LED 基准与遮挡数据
        self.baseline_bits: Optional[List[int]] = None
        self.baseline_recorded = False
        self.baseline_led_threshold = 94
        self.baseline_confirmation_duration = 3.0
        self.baseline_candidate_bits: Optional[List[int]] = None
        self.baseline_candidate_start_time: Optional[float] = None

        # 逻辑阵列维度（1 x 96）用于检测算法
        self.rows = 1
        self.cols = 96

        # 显示维度保留 8 x 12 以兼容现有前端布局
        self.display_rows = 8
        self.display_cols = 12

        # 遮挡与稳定性评估参数
        self.occlusion_history: deque[Tuple[float, int]] = deque(maxlen=120)
        self.occlusion_rate_window = 0.5
        self.occlusion_rate_threshold = 20.0
        self.occlusion_entry_threshold = 12
        self.last_occlusion_area = 0

        self.stability_history: deque[Tuple[float, int, float]] = deque()
        self.stability_window = 3.0
        self.stability_min_duration = 2.0
        self.stability_led_tolerance = 3
        self.stability_length_tolerance_cm = 0.8

        self.last_bits: Optional[List[int]] = None
        self.stable_state_start_time: Optional[float] = None
        self.stable_state_bits: Optional[List[int]] = None
        self.stable_duration_seconds = 1.0
        self.max_led_flash_count = 3

        self.foot_stable_start_time: Optional[float] = None
        self.foot_stable_duration_seconds = 3.0

        self.last_display_update_time: Optional[float] = None
        self.display_update_interval = 0.1

        self._invert_led_bits = self._parse_bool_env("DAYU_INVERT_BITS", False)

        # UI 相关缓存
        self._status_text = '请点击"开始检测"按钮'
        self._result_text = ""
        self._state: Dict[str, object] = {
            "is_detecting": False,
            "phase": "idle",
            "result": None,
        }

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

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def start_detection(self) -> None:
        if self.is_detecting:
            return

        self.stop_detection()
        self._reset_detection_state()

        self.is_detecting = True
        self.detection_phase = "waiting_baseline"
        self._emit_state(is_detecting=True, phase=self.detection_phase, result=None)
        self._set_status("请先保持设备空置，正在记录基准状态...")
        self._set_result("")

        try:
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
            self.serial_worker.led_bits_signal.connect(self._on_led_bits_received)
            self.serial_thread.finished.connect(self.serial_worker.deleteLater)
            self.serial_thread.start()
        except Exception as exc:  # pragma: no cover - 硬件异常
            self._handle_error(f"启动检测失败: {exc}")

    def stop_detection(self) -> None:
        if not self.is_detecting and self.detection_phase in {"idle", "completed"}:
            self._stop_serial_worker()
            return

        self.is_detecting = False
        self.detection_phase = "idle"
        self.result_foot_length = None
        self._emit_state(is_detecting=False, phase=self.detection_phase, result=None)
        self._set_status("检测已停止")
        self._stop_serial_worker()
        self._reset_runtime_buffers()

    def shutdown(self) -> None:
        self.stop_detection()

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _reset_detection_state(self) -> None:
        self.baseline_bits = None
        self.baseline_recorded = False
        self.baseline_candidate_bits = None
        self.baseline_candidate_start_time = None
        self.occlusion_history.clear()
        self.last_occlusion_area = 0
        self.stability_history.clear()
        self.last_bits = None
        self.stable_state_start_time = None
        self.stable_state_bits = None
        self.foot_detected = False
        self.foot_stable_start_time = None
        self.result_foot_length = None
        self.last_display_update_time = None

    def _reset_runtime_buffers(self) -> None:
        try:
            self.occlusion_history.clear()
        except Exception:
            pass
        try:
            self.stability_history.clear()
        except Exception:
            pass
        self.last_occlusion_area = 0
        self.last_bits = None
        self.stable_state_start_time = None
        self.stable_state_bits = None

    def _stop_serial_worker(self, wait_timeout: int = 2000) -> None:
        if self.serial_worker:
            try:
                self.serial_worker.led_bits_signal.disconnect(self._on_led_bits_received)
            except Exception:
                pass
            try:
                self.serial_worker.stop()
            except Exception:
                pass
        if self.serial_thread:
            try:
                self.serial_thread.quit()
                self.serial_thread.wait(wait_timeout)
            except Exception:
                pass
            finally:
                self.serial_thread = None
        self.serial_worker = None

    def _emit_state(self, **kwargs: object) -> None:
        self._state.update(kwargs)
        self.state_changed.emit(dict(self._state))

    def _set_status(self, text: str) -> None:
        if text == self._status_text:
            return
        self._status_text = text
        self.status_changed.emit(text)

    def _set_result(self, text: str) -> None:
        if text == self._result_text:
            return
        self._result_text = text
        self.result_text_changed.emit(text)

    def _append_result(self, text: str) -> None:
        new_text = text if not self._result_text else f"{self._result_text}\n{text}"
        self._set_result(new_text)

    def _handle_error(self, message: str) -> None:
        self.error_occurred.emit(message)
        self._set_status(message)
        self.stop_detection()

    # ------------------------------------------------------------------
    # 核心算法
    # ------------------------------------------------------------------
    def _count_led_changes(self, bits1: List[int], bits2: List[int]) -> int:
        if not bits1 or not bits2 or len(bits1) != len(bits2):
            return 999
        return sum(1 for a, b in zip(bits1, bits2) if a != b)

    def _is_stable_state(self, current_bits: List[int], current_time: float) -> bool:
        if self.last_bits is None:
            return False
        if self._count_led_changes(self.last_bits, current_bits) > self.max_led_flash_count:
            return False

        if self.stable_state_bits is not None:
            if current_bits == self.stable_state_bits:
                if self.stable_state_start_time is not None:
                    duration = current_time - self.stable_state_start_time
                    if duration >= self.stable_duration_seconds:
                        return True
            else:
                self.stable_state_bits = current_bits.copy()
                self.stable_state_start_time = current_time
                return False
        else:
            self.stable_state_bits = current_bits.copy()
            self.stable_state_start_time = current_time
            return False
        return False

    def _compute_occlusion_metrics(self, bits: List[int]) -> Tuple[int, int]:
        if self.baseline_bits is None:
            return 0, 0
        limit = min(len(bits), len(self.baseline_bits), 96)
        if limit <= 0:
            return 0, 0

        occluded_flags: List[int] = []
        total = 0
        for idx in range(limit):
            occluded = 1 if (self.baseline_bits[idx] == 0 and bits[idx] == 1) else 0
            occluded_flags.append(occluded)
            if occluded:
                total += 1

        max_len = 0
        current_len = 0
        for flag in occluded_flags:
            if flag:
                current_len += 1
                if current_len > max_len:
                    max_len = current_len
            else:
                current_len = 0
        return max_len, total

    def _update_occlusion_history(self, area: int, timestamp: float) -> float:
        self.occlusion_history.append((timestamp, area))
        while (
            len(self.occlusion_history) > 1
            and timestamp - self.occlusion_history[0][0] > self.occlusion_rate_window
        ):
            self.occlusion_history.popleft()
        if len(self.occlusion_history) <= 1:
            return 0.0
        dt = self.occlusion_history[-1][0] - self.occlusion_history[0][0]
        if dt <= 0:
            return 0.0
        return (self.occlusion_history[-1][1] - self.occlusion_history[0][1]) / dt

    def _update_stability_assessment(
        self,
        timestamp: float,
        occlusion_length: int,
        foot_length_cm: float,
    ) -> Tuple[bool, float]:
        if foot_length_cm <= 0:
            self.stability_history.clear()
            return False, 0.0
        if occlusion_length < self.occlusion_entry_threshold:
            self.stability_history.clear()
            return False, 0.0

        self.stability_history.append((timestamp, occlusion_length, foot_length_cm))
        while (
            self.stability_history
            and timestamp - self.stability_history[0][0] > self.stability_window
        ):
            self.stability_history.popleft()

        if not self.stability_history:
            return False, 0.0
        if timestamp - self.stability_history[0][0] < self.stability_min_duration:
            return False, 0.0

        occlusions = [item[1] for item in self.stability_history]
        if max(occlusions) - min(occlusions) > self.stability_led_tolerance:
            return False, 0.0

        lengths = [item[2] for item in self.stability_history]
        if lengths and max(lengths) - min(lengths) > self.stability_length_tolerance_cm:
            return False, 0.0

        avg_length = sum(lengths) / len(lengths) if lengths else 0.0
        return True, avg_length

    def _led_distribution_matches(self, reference: List[int], current: List[int]) -> bool:
        if reference is None or current is None:
            return False
        n = min(len(reference), len(current), 96)
        if any(reference[i] != current[i] for i in range(n)):
            return False
        if len(current) > n and any(current[i] for i in range(n, min(len(current), 96))):
            return False
        if len(reference) > n and any(reference[i] for i in range(n, min(len(reference), 96))):
            return False
        return True

    # ------------------------------------------------------------------
    # 硬件数据回调
    # ------------------------------------------------------------------
    @Slot(list)
    def _on_led_bits_received(self, bits: List[int]) -> None:
        try:
            if not isinstance(bits, (list, tuple)):
                return
            raw_bits = [1 if b else 0 for b in bits]
            if not raw_bits:
                return
            display_bits = raw_bits
            if self._invert_led_bits:
                display_bits = [0 if b else 1 for b in raw_bits]
            logic_bits = [0 if b else 1 for b in display_bits]
        except Exception as exc:
            self.error_occurred.emit(f"LED 数据格式错误: {exc}")
            return

        try:
            self.led_bits_signal.emit(display_bits)
        except Exception:
            pass

        if not self.is_detecting:
            return

        current_time = time.perf_counter()
        occlusion_largest = 0
        occlusion_rate = 0.0
        foot_length_estimate = 0.0

        if self.baseline_recorded and self.baseline_bits is not None:
            try:
                occlusion_largest, _ = self._compute_occlusion_metrics(logic_bits)
                occlusion_rate = self._update_occlusion_history(occlusion_largest, current_time)
            except Exception as exc:
                self.error_occurred.emit(f"遮挡LED数计算失败: {exc}")
                occlusion_largest = 0
                occlusion_rate = 0.0
            self.last_occlusion_area = occlusion_largest
            try:
                length_value = calculate_foot_length(
                    logic_bits,
                    baseline_bits=self.baseline_bits,
                    spacing_cm=self.spacing_cm,
                )
                if length_value is not None:
                    foot_length_estimate = length_value
            except Exception as exc:
                self.error_occurred.emit(f"脚长计算失败: {exc}")
                foot_length_estimate = 0.0
        else:
            self.occlusion_history.clear()
            self.last_occlusion_area = 0

        movement_detected = abs(occlusion_rate) > self.occlusion_rate_threshold

        try:
            is_stable_state = self._is_stable_state(logic_bits, current_time)
        except Exception as exc:
            self.error_occurred.emit(f"状态判断失败: {exc}")
            is_stable_state = False
        if movement_detected:
            is_stable_state = False

        self.last_bits = logic_bits.copy()

        try:
            self._process_detection_phase(
                logic_bits,
                current_time,
                occlusion_largest,
                occlusion_rate,
                movement_detected,
                foot_length_estimate,
                is_stable_state,
            )
        except Exception as exc:  # pragma: no cover - 防御性捕获
            self.error_occurred.emit(f"检测阶段处理失败: {exc}")

    # ------------------------------------------------------------------
    # 阶段状态机
    # ------------------------------------------------------------------
    def _process_detection_phase(
        self,
        bits: List[int],
        current_time: float,
        occlusion_largest: int,
        occlusion_rate: float,
        movement_detected: bool,
        foot_length_estimate: float,
        is_stable_state: bool,
    ) -> None:
        if self.detection_phase == "waiting_baseline":
            self._handle_waiting_baseline(bits, current_time)
            return

        if self.detection_phase == "waiting_foot":
            self._handle_waiting_foot(occlusion_largest, occlusion_rate)
            return

        if self.detection_phase == "detecting":
            self._handle_detecting(
                bits,
                current_time,
                occlusion_largest,
                occlusion_rate,
                movement_detected,
                foot_length_estimate,
            )
            return

    def _handle_waiting_baseline(self, bits: List[int], current_time: float) -> None:
        lit_count = sum(1 for b in bits[: min(len(bits), 96)] if b == 0)
        threshold = self.baseline_led_threshold

        if lit_count >= threshold:
            if self.baseline_candidate_bits is None:
                self.baseline_candidate_bits = bits.copy()
                self.baseline_candidate_start_time = current_time
            else:
                if not self._led_distribution_matches(self.baseline_candidate_bits, bits):
                    self.baseline_candidate_bits = bits.copy()
                    self.baseline_candidate_start_time = current_time

            if self.baseline_candidate_start_time is not None:
                duration = current_time - self.baseline_candidate_start_time
                if duration >= self.baseline_confirmation_duration:
                    try:
                        self.baseline_bits = self.baseline_candidate_bits.copy()
                        self.baseline_recorded = True
                        self.detection_phase = "waiting_foot"
                        self._emit_state(phase=self.detection_phase)
                        self.occlusion_history.clear()
                        self.last_occlusion_area = 0
                        self.stability_history.clear()
                        self.baseline_candidate_bits = None
                        self.baseline_candidate_start_time = None
                        self._set_status("初始化完成，请将一只脚平行放入设备")
                        self._set_result("初始化完成。\n请将一只脚平行放入设备，保持稳定。")
                    except Exception as exc:
                        self.error_occurred.emit(f"记录基准状态失败: {exc}")
                        self.baseline_candidate_bits = None
                        self.baseline_candidate_start_time = None
                    return
                if (
                    self.last_display_update_time is None
                    or current_time - self.last_display_update_time >= self.display_update_interval
                ):
                    progress = min(int((duration / self.baseline_confirmation_duration) * 100), 100)
                    self._set_status(
                        f"初始化中... {duration:.1f}s / {self.baseline_confirmation_duration:.1f}s ({progress}%)"
                    )
                    self._set_result(
                        f"检测亮灯数: {lit_count}\n"
                        f"初始化中... {duration:.1f}s / {self.baseline_confirmation_duration:.1f}s"
                    )
                    self.last_display_update_time = current_time
        else:
            self.baseline_candidate_bits = None
            self.baseline_candidate_start_time = None
            if (
                self.last_display_update_time is None
                or current_time - self.last_display_update_time >= self.display_update_interval
            ):
                self._set_status("请先清空设备表面，等待亮灯恢复...")
                self._set_result(f"当前亮灯数: {lit_count}\n等待所有 LED 恢复亮起...")
                self.last_display_update_time = current_time

    def _handle_waiting_foot(self, occlusion_largest: int, occlusion_rate: float) -> None:
        if self.baseline_bits is None:
            self.detection_phase = "waiting_baseline"
            self._emit_state(phase=self.detection_phase)
            self.occlusion_history.clear()
            return

        area = occlusion_largest
        rate_abs = abs(occlusion_rate)

        if area >= self.occlusion_entry_threshold and rate_abs <= self.occlusion_rate_threshold:
            self.foot_detected = True
            self.detection_phase = "detecting"
            self._emit_state(phase=self.detection_phase)
            self.foot_stable_start_time = None
            self._set_status("检测到脚迈入，等待稳定状态...")
            self._set_result(
                "检测到脚迈入。\n"
                f"遮挡LED数: {area} 个\n"
                f"遮挡变化速率: {rate_abs:.1f} LED/s\n"
                "等待脚保持稳定..."
            )
        else:
            if self.last_display_update_time is None:
                should_update = True
            else:
                should_update = (
                    time.perf_counter() - self.last_display_update_time
                    >= self.display_update_interval
                )
            if should_update:
                if area >= self.occlusion_entry_threshold:
                    self._set_status("脚正在移动，请保持脚平行放置并保持不动...")
                    detail = "脚正在移动，请保持不动..."
                else:
                    self._set_status("等待脚迈入... 请将脚平行放在设备上")
                    detail = "等待脚迈入..."
                self._set_result(
                    f"遮挡LED数: {area} 个\n"
                    f"遮挡变化速率: {rate_abs:.1f} LED/s\n"
                    f"{detail}"
                )
                self.last_display_update_time = time.perf_counter()

    def _handle_detecting(
        self,
        bits: List[int],
        current_time: float,
        occlusion_largest: int,
        occlusion_rate: float,
        movement_detected: bool,
        foot_length_estimate: float,
    ) -> None:
        if movement_detected:
            self.stability_history.clear()
            self.foot_stable_start_time = None
        if occlusion_largest < self.occlusion_entry_threshold:
            self.stability_history.clear()
            self.foot_stable_start_time = None
            if (
                self.last_display_update_time is None
                or current_time - self.last_display_update_time >= self.display_update_interval
            ):
                self._set_status("遮挡LED数不足，请确保脚完全贴合设备...")
                self._set_result(
                    f"遮挡LED数: {occlusion_largest} 个\n"
                    f"遮挡变化速率: {abs(occlusion_rate):.1f} LED/s\n"
                    "请保持稳定"
                )
                self.last_display_update_time = current_time
            return

        stability_ready = False
        stable_length_cm = 0.0
        if foot_length_estimate > 0:
            stability_ready, stable_length_cm = self._update_stability_assessment(
                current_time,
                occlusion_largest,
                foot_length_estimate,
            )
        else:
            self.stability_history.clear()
        if movement_detected:
            stability_ready = False
            self.stability_history.clear()

        if stability_ready:
            foot_length = stable_length_cm if stable_length_cm > 0 else foot_length_estimate
            if foot_length <= 0:
                foot_length = calculate_foot_length(
                    bits,
                    baseline_bits=self.baseline_bits,
                    spacing_cm=self.spacing_cm,
                ) or 0.0
            if foot_length > 0:
                self.result_foot_length = foot_length
                self.detection_phase = "completed"
                self.is_detecting = False
                self._emit_state(
                    is_detecting=False,
                    phase=self.detection_phase,
                    result=foot_length,
                )
                self._stop_serial_worker()
                self.stability_history.clear()
                self.foot_stable_start_time = None
                self._set_status(f"检测完成！脚长: {foot_length:.2f} cm")
                summary = (
                    "——" * 30
                    + "\n检测完成！\n"
                    + f"脚长: {foot_length:.2f} cm\n"
                    + f"遮挡LED数: {occlusion_largest} 个\n"
                    + f"遮挡变化速率: {abs(occlusion_rate):.1f} LED/s\n"
                    + f"检测时间: {time.strftime('%H:%M:%S')}\n"
                    + "——" * 30
                )
                self._append_result(summary)
                self.detection_completed.emit(
                    foot_length,
                    {
                        "occlusion_leds": occlusion_largest,
                        "occlusion_rate": abs(occlusion_rate),
                        "timestamp": time.time(),
                    },
                )
                return
            self.stability_history.clear()

        if (
            self.last_display_update_time is None
            or current_time - self.last_display_update_time >= self.display_update_interval
        ):
            message = "脚正在移动，请保持不动..." if movement_detected else "请保持稳定"
            self._set_status(message)
            self._set_result(
                f"遮挡LED数: {occlusion_largest} 个\n"
                f"遮挡变化速率: {abs(occlusion_rate):.1f} LED/s\n"
                f"当前估计脚长: {foot_length_estimate:.2f} cm\n"
                f"{message}"
            )
            self.last_display_update_time = current_time
