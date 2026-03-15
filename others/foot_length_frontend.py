'''测脚长前端界面'''
from __future__ import annotations

from typing import Dict, List, Optional

from qtpy import QtWidgets
from qtpy.QtCore import Qt, Slot
from dayu_widgets import dayu_theme
from dayu_widgets.divider import MDivider
from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton
from dayu_widgets.text_edit import MTextEdit
from dayu_widgets.qt import application

from foot_length_backend import FootLengthBackend
from led_con import LEDPanel

__all__ = ["FootLengthWidget", "launch"]


class FootLengthWidget(QtWidgets.QWidget):
    """脚长检测前端界面，负责展示与用户交互。"""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.backend = FootLengthBackend(self)

        self._init_ui()
        self._connect_backend()

        # 初始按钮状态
        self._handle_state_change({"is_detecting": False, "phase": "idle", "result": None})
        self.status_label.setText('请点击"开始检测"按钮')

    # ------------------------------------------------------------------
    # UI 构建与信号连接
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        self.setWindowTitle("脚长检测")
        self.setMinimumSize(800, 600)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        title_label = MLabel("脚长检测")
        title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title_label.setStyleSheet("font-size: 18pt; font-weight: bold;")
        main_layout.addWidget(title_label)

        main_layout.addWidget(MDivider("设备状态"))

        self.status_label = MLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.status_label.setStyleSheet("font-size: 12pt; color: #666; padding: 10px;")
        main_layout.addWidget(self.status_label)

        content_layout = QtWidgets.QHBoxLayout()
        content_layout.setSpacing(20)
        main_layout.addLayout(content_layout)

        # 左侧 LED 展示
        left_panel = QtWidgets.QVBoxLayout()
        left_panel.addWidget(MDivider("LED 阵列"))
        display_rows = getattr(self.backend, "display_rows", self.backend.rows)
        display_cols = getattr(self.backend, "display_cols", self.backend.cols)
        self.led_panel = LEDPanel(rows=display_rows, cols=display_cols, parent=self)
        self.led_panel.setMinimumSize(300, 200)
        left_panel.addWidget(self.led_panel)
        left_panel.addStretch()
        content_layout.addLayout(left_panel, 1)

        # 右侧结果区域
        right_panel = QtWidgets.QVBoxLayout()
        right_panel.addWidget(MDivider("检测结果"))

        self.result_text = MTextEdit(self)
        self.result_text.setReadOnly(True)
        self.result_text.setMinimumHeight(200)
        self.result_text.setStyleSheet("QTextEdit { font-family: 'Consolas', monospace; font-size: 11pt; }")
        right_panel.addWidget(self.result_text)
        content_layout.addLayout(right_panel, 1)

        # 底部按钮
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        self.btn_start = MPushButton("开始检测").primary()
        self.btn_start.setMinimumSize(120, 48)
        self.btn_start.clicked.connect(self._on_start_clicked)
        button_layout.addWidget(self.btn_start)

        self.btn_stop = MPushButton("停止检测")
        self.btn_stop.setMinimumSize(120, 48)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        button_layout.addWidget(self.btn_stop)
        button_layout.addStretch()
        main_layout.addLayout(button_layout)

        main_layout.addStretch()

    def _connect_backend(self) -> None:
        self.backend.led_bits_signal.connect(self._update_led_panel)
        self.backend.status_changed.connect(self._update_status_text)
        self.backend.result_text_changed.connect(self._update_result_text)
        self.backend.state_changed.connect(self._handle_state_change)
        self.backend.error_occurred.connect(self._handle_error)
        self.backend.detection_completed.connect(self._handle_detection_completed)

    # ------------------------------------------------------------------
    # Qt 事件
    # ------------------------------------------------------------------
    def closeEvent(self, event: QtWidgets.QCloseEvent) -> None:  # noqa: N802
        try:
            self.backend.shutdown()
        finally:
            super().closeEvent(event)

    # ------------------------------------------------------------------
    # 槽函数
    # ------------------------------------------------------------------
    @Slot()
    def _on_start_clicked(self) -> None:
        self.backend.start_detection()

    @Slot()
    def _on_stop_clicked(self) -> None:
        self.backend.stop_detection()

    @Slot(list)
    def _update_led_panel(self, bits: List[int]) -> None:
        try:
            self.led_panel.set_leds(bits)
        except Exception:
            # 前端显示失败不应影响后端逻辑
            pass

    @Slot(str)
    def _update_status_text(self, text: str) -> None:
        self.status_label.setText(text)

    @Slot(str)
    def _update_result_text(self, text: str) -> None:
        scrollbar = self.result_text.verticalScrollBar()
        stick_to_bottom = False
        if scrollbar is not None:
            stick_to_bottom = scrollbar.value() >= scrollbar.maximum() - 5
        self.result_text.setPlainText(text)
        if scrollbar is not None and stick_to_bottom:
            scrollbar.setValue(scrollbar.maximum())

    @Slot(dict)
    def _handle_state_change(self, state: Dict[str, object]) -> None:
        detecting = bool(state.get("is_detecting", False))
        phase = state.get("phase", "idle")
        self.btn_start.setEnabled(not detecting)
        self.btn_stop.setEnabled(detecting)
        if phase == "completed":
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)

    @Slot(str)
    def _handle_error(self, message: str) -> None:
        self.status_label.setText(message)
        QtWidgets.QMessageBox.warning(self, "检测错误", message)

    @Slot(float, dict)
    def _handle_detection_completed(self, length_cm: float, meta: Dict[str, object]) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "检测完成",
            f"脚长: {length_cm:.2f} cm\n遮挡LED数: {meta.get('occlusion_leds', '未知')} 个",
        )


def launch() -> int:
    """作为独立程序运行脚长检测界面。"""
    with application() as app:
        widget = FootLengthWidget()
        dayu_theme.apply(widget)
        widget.show()
        return app.exec_()


if __name__ == "__main__":
    raise SystemExit(launch())
