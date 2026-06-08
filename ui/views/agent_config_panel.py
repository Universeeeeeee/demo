"""Agent-assisted test configuration panel for SetupView."""

from __future__ import annotations

import logging
import traceback

from markdown_it import MarkdownIt
from qtpy.QtCore import Qt, Signal, QThread, QTimer
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QComboBox, QTextEdit,
    QFrame, QSizePolicy,
)

from dayu_widgets.divider import MDivider
from dayu_widgets.label import MLabel
from dayu_widgets.line_edit import MLineEdit
from dayu_widgets.push_button import MPushButton
from dayu_widgets.spin_box import MDoubleSpinBox, MSpinBox

from agent.models import AthleteProfile
from agent.rule_engine import RuleEngine
from config.test_config import TestConfig
from data.subject_store import SubjectSearchResult, SubjectStore
from ui.llm_client import LLMWorkerClient


log = logging.getLogger(__name__)
_md = MarkdownIt().enable("table")


def _md_to_html(text: str) -> str:
    return _md.render(text)


class _LLMHttpWorker(QThread):
    """在线模式：通过 HTTP 调用 llm_worker 进程（阻塞式，v1 无流式）。"""
    finished = Signal(object, str)  # (TestConfig | None, reply_text)
    error = Signal(str)

    def __init__(self, client: LLMWorkerClient, message: str, athlete: AthleteProfile):
        super().__init__()
        self._client = client
        self._message = message
        self._athlete = athlete

    def run(self):
        try:
            profile_dict = {
                "age": self._athlete.age,
                "weight": self._athlete.weight,
                "height": self._athlete.height,
                "level": self._athlete.level,
                "focus_side": self._athlete.focus_side,
                "device_channels": self._athlete.device_channels,
                "history": self._athlete.history,
            }
            result = self._client.chat(self._message, profile_dict)
            if "error" in result:
                self.error.emit(result["error"])
                return
            config_dict = result.get("config")
            if config_dict:
                config = TestConfig(**config_dict)
            else:
                config = None
            self.finished.emit(config, result.get("reply", ""))
        except Exception as e:
            self.error.emit(f"{e}\n{traceback.format_exc()}")


class AgentConfigPanel(QWidget):
    """智能配置面板：生成建议配置，确认后交给 SetupView。"""

    config_confirmed = Signal(object)  # TestConfig

    def __init__(
        self,
        subject_store: SubjectStore | None = None,
        llm_client: LLMWorkerClient | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._subject_store = subject_store
        self._llm_client = llm_client
        self._rule_engine = RuleEngine()
        self._llm_worker: _LLMHttpWorker | None = None
        self._worker_ready = False
        self._worker_error: str | None = None
        self._worker_start_requested = False
        self._pending_config: TestConfig | None = None
        self._history: list[dict] = []
        self._worker_status_timer = QTimer(self)
        self._worker_status_timer.setInterval(1000)
        self._worker_status_timer.timeout.connect(self._poll_llm_worker)

        self._build_ui()
        self._connect_signals()
        self.set_subject_result(None)
        self._sync_mode_state()
        QTimer.singleShot(0, self._ensure_llm_worker_started)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_subject_result(self, result: SubjectSearchResult | None) -> None:
        self._clear_pending_config()
        self._history = []
        if result is None or self._subject_store is None:
            self._fill_athlete_fields(
                AthleteProfile(age=30, weight=70, height=170, level="intermediate")
            )
            self._profile_note.setText("未选择受试者，请填写基础信息。仅用于本次配置。")
            self._history_label.setText("历史记录：暂无")
            return

        try:
            self._history = self._subject_store.get_recent_history(result.subject.id)
            profile = self._subject_store.subject_to_athlete_profile(
                result.subject, self._history,
            )
        except Exception:
            log.exception("Failed to load subject profile for agent panel")
            profile = AthleteProfile(age=30, weight=70, height=170)
            self._history = []

        self._fill_athlete_fields(profile)
        self._profile_note.setText("已从受试者档案自动填入，可修改。仅用于本次配置。")
        count_text = f"最近 {len(self._history)} 次已加载" if self._history else "暂无"
        self._history_label.setText(f"历史记录：{count_text}")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)

        profile_card = self._create_card()
        profile_layout = QVBoxLayout(profile_card)
        profile_layout.setContentsMargins(16, 14, 16, 14)
        profile_layout.setSpacing(10)
        profile_layout.addWidget(MDivider("运动档案"))

        self._profile_note = MLabel("")
        self._profile_note.setWordWrap(True)
        self._profile_note.setStyleSheet("color: #9f9f9f;")
        profile_layout.addWidget(self._profile_note)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)
        self._age_spin = MSpinBox()
        self._age_spin.setRange(1, 120)
        self._weight_spin = MDoubleSpinBox()
        self._weight_spin.setRange(0, 300)
        self._weight_spin.setSuffix(" kg")
        self._height_spin = MDoubleSpinBox()
        self._height_spin.setRange(0, 250)
        self._height_spin.setSuffix(" cm")
        self._level_combo = QComboBox()
        self._level_combo.addItems(["beginner", "intermediate", "advanced"])
        self._focus_combo = QComboBox()
        self._focus_combo.addItem("均衡", "")
        self._focus_combo.addItem("左侧", "left")
        self._focus_combo.addItem("右侧", "right")
        self._focus_combo.addItem("双侧", "both")

        self._add_form_row(form, 0, "年龄", self._age_spin)
        self._add_form_row(form, 1, "体重", self._weight_spin)
        self._add_form_row(form, 2, "身高", self._height_spin)
        self._add_form_row(form, 3, "训练水平", self._level_combo)
        self._add_form_row(form, 4, "侧重训练", self._focus_combo)
        profile_layout.addLayout(form)

        self._history_label = MLabel("")
        self._history_label.setStyleSheet("color: #aaaaaa;")
        profile_layout.addWidget(self._history_label)
        profile_layout.addStretch()
        profile_card.setMinimumWidth(260)
        profile_card.setMaximumWidth(320)
        main_layout.addWidget(profile_card)

        chat_card = self._create_card()
        chat_layout = QVBoxLayout(chat_card)
        chat_layout.setContentsMargins(16, 14, 16, 14)
        chat_layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(MDivider("配置助手"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["在线 LLM", "离线规则"])
        self._mode_combo.setMaximumWidth(160)
        header.addWidget(self._mode_combo)
        chat_layout.addLayout(header)

        self._status_label = MLabel("")
        self._status_label.setStyleSheet("color: #d8a443;")
        chat_layout.addWidget(self._status_label)

        self._chat_display = QTextEdit()
        self._chat_display.setReadOnly(True)
        self._chat_display.setPlaceholderText("对话记录...")
        self._chat_display.document().setDefaultStyleSheet(
            "table { border-collapse: collapse; margin: 8px 0; }"
            "td, th { border: 1px solid #999; padding: 4px 10px; }"
        )
        chat_layout.addWidget(self._chat_display, 1)

        chip_layout = QHBoxLayout()
        for text in ("入门用户 3 次纵跳", "普通用户 5 次纵跳", "按 1 分钟测试", "轻量测试"):
            chip = MPushButton(text)
            chip.clicked.connect(lambda _, value=text: self._chat_input.setText(value))
            chip_layout.addWidget(chip)
        chip_layout.addStretch()
        chat_layout.addLayout(chip_layout)

        input_layout = QHBoxLayout()
        self._chat_input = MLineEdit()
        self._chat_input.setPlaceholderText("描述测试需求...")
        self._send_btn = MPushButton("发送").primary()
        self._reset_btn = MPushButton("重置对话")
        self._offline_btn = MPushButton("生成离线推荐")
        input_layout.addWidget(self._chat_input, 1)
        input_layout.addWidget(self._send_btn)
        input_layout.addWidget(self._reset_btn)
        input_layout.addWidget(self._offline_btn)
        chat_layout.addLayout(input_layout)
        main_layout.addWidget(chat_card, 1)

        suggestion_card = self._create_card()
        suggestion_layout = QVBoxLayout(suggestion_card)
        suggestion_layout.setContentsMargins(16, 14, 16, 14)
        suggestion_layout.setSpacing(10)
        suggestion_layout.addWidget(MDivider("建议配置"))

        self._suggestion_text = MLabel("尚未生成建议配置。")
        self._suggestion_text.setWordWrap(True)
        self._suggestion_text.setStyleSheet("font-size: 11pt; color: #d0d0d0;")
        suggestion_layout.addWidget(self._suggestion_text, 1)

        self._confirm_btn = MPushButton("确认使用此配置").primary()
        self._confirm_btn.setEnabled(False)
        suggestion_layout.addWidget(self._confirm_btn)
        suggestion_card.setMinimumWidth(300)
        suggestion_card.setMaximumWidth(360)
        main_layout.addWidget(suggestion_card)

    def _connect_signals(self) -> None:
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._send_btn.clicked.connect(self._on_send_message)
        self._chat_input.returnPressed.connect(self._on_send_message)
        self._reset_btn.clicked.connect(self._on_reset_chat)
        self._offline_btn.clicked.connect(self._on_offline_generate)
        self._confirm_btn.clicked.connect(self._on_confirm_clicked)
        self._age_spin.valueChanged.connect(self._clear_pending_config)
        self._weight_spin.valueChanged.connect(self._clear_pending_config)
        self._height_spin.valueChanged.connect(self._clear_pending_config)
        self._level_combo.currentIndexChanged.connect(self._clear_pending_config)
        self._focus_combo.currentIndexChanged.connect(self._clear_pending_config)

    def _create_card(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background-color: rgba(35, 35, 40, 0.65); "
            "border: 1px solid rgba(120, 120, 120, 0.25); border-radius: 6px; }"
        )
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return frame

    @staticmethod
    def _add_form_row(layout: QGridLayout, row: int, label: str, widget: QWidget) -> None:
        layout.addWidget(MLabel(label), row, 0)
        layout.addWidget(widget, row, 1)

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _fill_athlete_fields(self, profile: AthleteProfile) -> None:
        self._age_spin.setValue(profile.age)
        self._weight_spin.setValue(float(profile.weight or 0.0))
        self._height_spin.setValue(float(profile.height or 0.0))
        index = self._level_combo.findText(profile.level)
        if index >= 0:
            self._level_combo.setCurrentIndex(index)
        focus_index = self._focus_combo.findData(profile.focus_side)
        self._focus_combo.setCurrentIndex(max(focus_index, 0))

    def _current_athlete_profile(self) -> AthleteProfile:
        return AthleteProfile(
            age=self._age_spin.value(),
            weight=float(self._weight_spin.value()),
            height=float(self._height_spin.value()),
            level=self._level_combo.currentText(),
            focus_side=self._focus_combo.currentData() or "",
            history=list(self._history),
        )

    def _clear_pending_config(self, *_args) -> None:
        if self._pending_config is None:
            return
        self._pending_config = None
        self._confirm_btn.setEnabled(False)
        self._suggestion_text.setText("运动档案已变化，请重新生成建议配置。")

    def _sync_mode_state(self) -> None:
        online = self._mode_combo.currentIndex() == 0
        busy = self._llm_worker is not None and self._llm_worker.isRunning()
        if self._llm_client is not None and not self._llm_client.is_running:
            self._worker_ready = False
        self._offline_btn.setEnabled(not online and not busy)
        self._chat_input.setEnabled(online and not busy and self._worker_ready)
        self._send_btn.setEnabled(online and not busy and self._worker_ready)
        self._reset_btn.setEnabled(not busy and (not online or self._worker_ready))
        if online:
            if self._llm_client is None:
                self._status_label.setText("智能服务未初始化。")
            elif self._worker_error:
                self._status_label.setText(f"智能模块初始化失败：{self._worker_error}")
            elif not self._worker_ready:
                self._status_label.setText("智能模块正在初始化，请稍候。")
            elif busy:
                self._status_label.setText("正在生成建议...")
            else:
                self._status_label.setText("在线 LLM 已就绪。")
        else:
            self._status_label.setText("离线规则不依赖网络，根据运动档案生成保守配置。")

    def _ensure_llm_worker_started(self) -> None:
        if self._mode_combo.currentIndex() != 0 or self._llm_client is None:
            self._sync_mode_state()
            return
        if self._worker_ready:
            self._sync_mode_state()
            return
        if not self._llm_client.is_running:
            self._worker_start_requested = True
            self._worker_error = None
            if not self._llm_client.start():
                self._worker_error = "worker 进程启动失败"
                self._sync_mode_state()
                return
        if not self._worker_status_timer.isActive():
            self._worker_status_timer.start()
        self._poll_llm_worker()

    def _poll_llm_worker(self) -> None:
        if self._llm_client is None:
            return
        status = self._llm_client.worker_status(timeout=0.25)
        if status == "ready":
            self._worker_ready = True
            self._worker_error = None
            self._worker_status_timer.stop()
        elif status in {"starting", "warming"}:
            self._worker_ready = False
            self._worker_error = None
        else:
            self._worker_ready = False
            self._worker_error = status
            self._worker_status_timer.stop()
        self._sync_mode_state()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_mode_changed(self, _index: int) -> None:
        if self._mode_combo.currentIndex() == 0:
            self._ensure_llm_worker_started()
            return
        self._sync_mode_state()

    def _on_send_message(self) -> None:
        if self._llm_worker is not None and self._llm_worker.isRunning():
            return
        if self._llm_client is None:
            return
        if not self._worker_ready:
            self._ensure_llm_worker_started()
            return
        message = self._chat_input.text().strip()
        if not message:
            return

        self._chat_display.append(f"<b>你:</b> {message}")

        self._chat_input.clear()

        self._llm_worker = _LLMHttpWorker(
            self._llm_client, message, self._current_athlete_profile(),
        )
        self._llm_worker.finished.connect(self._on_llm_finished)
        self._llm_worker.error.connect(self._on_llm_error)
        self._chat_input.setEnabled(False)
        self._send_btn.setEnabled(False)
        self._status_label.setText("正在生成建议...")
        self._llm_worker.start()

    def _on_llm_finished(self, config, reply: str) -> None:
        self._chat_display.append("<b>AI:</b> ")
        self._chat_display.insertHtml(_md_to_html(reply))

        if config is not None:
            self._set_pending_config(config, "在线 LLM 已生成建议配置。")

        self._llm_worker = None
        self._sync_mode_state()

    def _on_llm_error(self, message: str) -> None:
        self._chat_display.append(f"<b>错误:</b> {message}")
        self._llm_worker = None
        self._sync_mode_state()

    def _on_reset_chat(self) -> None:
        if self._llm_client is not None and self._worker_ready:
            self._llm_client.reset()
        self._pending_config = None
        self._confirm_btn.setEnabled(False)
        self._suggestion_text.setText("尚未生成建议配置。")
        self._chat_display.clear()

    def _on_offline_generate(self) -> None:
        try:
            config = self._rule_engine.configure(
                "Jump Test", self._current_athlete_profile(),
            )
        except Exception as e:
            self._chat_display.append(f"<b>错误:</b> 离线推荐失败：{e}")
            return

        self._set_pending_config(config, "离线规则已生成建议配置。")
        self._chat_display.append("<b>AI:</b> 已根据运动档案生成离线规则推荐。")

    def _on_confirm_clicked(self) -> None:
        if self._pending_config is None:
            return
        self._chat_display.append("<b>AI:</b> 配置已应用到参数面板。")
        self.config_confirmed.emit(self._pending_config)

    # ------------------------------------------------------------------
    # Suggestion card
    # ------------------------------------------------------------------

    def _set_pending_config(self, config: TestConfig, reason: str) -> None:
        self._pending_config = config
        self._confirm_btn.setEnabled(True)
        self._suggestion_text.setText(self._format_config(config, reason))

    def _format_config(self, config: TestConfig, reason: str) -> str:
        stop_labels = {
            "Status change": "按跳跃次数结束",
            "End of Time": f"按测试时长结束（{config.test_length}）",
            "External impulse": "手动控制结束",
        }
        start_labels = {
            "Status change": "踩上设备后开始",
            "External impulse": "手动开始",
        }
        position_labels = {
            "Inside area": "设备内",
            "Outside area": "设备外",
        }
        foot_labels = {
            "Not defined": "双脚 / 不限定",
            "Right": "右脚",
            "Left": "左脚",
        }
        lines = [
            f"测试类型：{config.mode_label}",
            f"结束方式：{stop_labels.get(config.stop_type, config.stop_type)}",
        ]
        if config.number_of_jumps:
            lines.append(f"目标跳跃：{config.number_of_jumps} 次")
        if config.test_length:
            lines.append(f"测试时长：{config.test_length}")
        lines.extend([
            f"开始方式：{start_labels.get(config.start_type, config.start_type)}",
            f"起始位置：{position_labels.get(config.start_position, config.start_position)}",
            f"起跳脚：{foot_labels.get(config.starting_foot, config.starting_foot)}",
            f"节拍器：{'开启' if config.metronome_enabled else '关闭'}",
            "",
            f"推荐理由：{reason}",
        ])
        return "\n".join(lines)
