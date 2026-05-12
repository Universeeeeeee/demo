"""
setup_view.py — 测试配置页

复用现有 ParamPanel，提供配置摘要和"准备就绪"按钮。
用户确认配置后，发射 ready_signal(TestConfig) 通知 MainWindow。
"""

from __future__ import annotations

from qtpy.QtCore import Signal, Qt
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QFrame, QSizePolicy,
)

from dayu_widgets.divider import MDivider
from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton

from ui.param_panel import ParamPanel


class SetupView(QWidget):
    """测试配置视图 — 参数面板 + 配置摘要 + 准备就绪按钮。"""

    ready_signal = Signal(object)  # TestConfig

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(12)

        # ===== 标题区 =====
        title = MLabel(" IronJump 步态分析系统")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 22pt; font-weight: bold; "
            "color: #e0e0e0; padding: 10px 0;"
        )
        layout.addWidget(title)

        # ===== 参数面板 (带滚动区) =====
        self.param_panel = ParamPanel()
        scroll = QScrollArea()
        scroll.setWidget(self.param_panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(scroll, 1)

        # ===== 配置摘要 =====
        layout.addWidget(MDivider("配置摘要"))
        self._summary_label = MLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(
            "font-size: 12pt; color: #b0b0b0; padding: 8px 12px; "
            "background-color: rgba(40, 40, 45, 0.6); border-radius: 6px;"
        )
        self._summary_label.setMinimumHeight(60)
        layout.addWidget(self._summary_label)

        # ===== 准备就绪按钮 =====
        self.btn_ready = MPushButton("✅ 准备就绪，开始测试").primary()
        self.btn_ready.setMinimumHeight(60)
        self.btn_ready.setStyleSheet(
            "font-size: 18pt; font-weight: bold; border-radius: 8px;"
        )
        self.btn_ready.clicked.connect(self._on_ready_clicked)
        layout.addWidget(self.btn_ready)

        # ===== 连接参数变更 → 更新摘要 =====
        self.param_panel.config_changed.connect(self._update_summary)
        self._update_summary()

    def _update_summary(self):
        """根据当前 ParamPanel 状态更新配置摘要文本。"""
        config = self.param_panel.get_config()
        lines = [
            f"测试模式: {config.test_type}",
            f"启动: {config.start_type}  |  停止: {config.stop_type}",
        ]
        if config.number_of_jumps:
            lines.append(f"目标跳跃: {config.number_of_jumps} 次")
        if config.test_length:
            lines.append(f"测试时长: {config.test_length}")
        lines.append(
            f"接触/腾空阈值: >{config.min_contact_time}ms / >{config.min_flight_time}ms"
        )
        if config.metronome_enabled:
            lines.append(f"节拍器: {config.metronome_bpm} BPM")

        self._summary_label.setText("\n".join(lines))

    def _on_ready_clicked(self):
        """收集配置并发射信号。"""
        config = self.param_panel.get_config()
        self.ready_signal.emit(config)
