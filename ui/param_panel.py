"""
param_panel.py — Jump Test 参数配置面板

动态生成表单控件，处理 stop_type 联动显隐，
对外提供 get_config() -> TestConfig 接口。

使用 dayu_widgets 保持 UI 风格统一:
  - MLabel:       标签
  - MDivider:     分组标题
  - MSpinBox:     整数输入
  - MTimeEdit:    时间输入 (mm:ss)
  - MSwitch:      布尔开关
  - MSectionItem: 折叠面板
  - QComboBox:    枚举选择 (标准控件, 避免 MComboBox 点击问题)
"""

from __future__ import annotations

from qtpy.QtCore import Signal, Qt, QTime
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QComboBox, QSizePolicy,
)

from dayu_widgets.divider import MDivider
from dayu_widgets.label import MLabel
from dayu_widgets.spin_box import MSpinBox, MTimeEdit
from dayu_widgets.switch import MSwitch
from dayu_widgets.collapse import MSectionItem

from config.param_schema import ParamSchema, ParamDef, get_schema
from config.test_config import AnyTestConfig, TestConfig


class ParamPanel(QWidget):
    """
    动态参数配置面板。

    根据 ParamSchema 和当前 test_type 生成表单，
    处理 stop_type / metronome_enabled 联动显隐。
    """

    config_changed = Signal()
    """参数变更信号。任何参数控件值变化时发射。"""

    # Layer 2 参数的创建顺序
    _LAYER2_PARAMS = [
        "start_type", "start_position", "stop_type",
        "finish_position", "number_of_jumps", "test_length",
        "starting_foot",
    ]

    # 受 stop_type 联动影响的字段
    _CONDITIONAL_FIELDS = ["finish_position", "number_of_jumps", "test_length"]

    # Layer 3 滤波参数
    _LAYER3_PARAMS = ["min_contact_time", "min_flight_time", "max_flight_time"]

    def __init__(self, parent=None):
        super().__init__(parent)

        self._schema: ParamSchema = get_schema()
        self._test_type: str = "Jump Test"

        # 参数名 → 输入控件 (QComboBox / MSpinBox / MTimeEdit / MSwitch)
        self._widgets: dict[str, QWidget] = {}
        # 参数名 → 整行容器 QWidget (用于 show/hide)
        self._rows: dict[str, QWidget] = {}

        self._filter_section: MSectionItem | None = None
        self._optional_section: MSectionItem | None = None

        self._build_ui()
        self._connect_signals()
        self._refresh_visibility()

    # ==================================================================
    #  公共方法
    # ==================================================================

    def get_config(self) -> AnyTestConfig:
        """收集所有控件当前值，构建 TestConfig。不可见的条件字段设为 None。"""
        values = self._current_values()

        # 获取当前可见参数
        visible_params = self._schema.get_visible_params(self._test_type, values)
        visible_names = {p.name for p in visible_params}

        config = TestConfig()
        config.test_type = self._test_type
        config.start_type = values.get("start_type", "Status change")
        config.start_position = values.get("start_position", "Inside area")
        config.stop_type = values.get("stop_type", "Status change")

        # 条件字段: 仅在可见时赋值
        config.finish_position = (
            values.get("finish_position") if "finish_position" in visible_names else None
        )
        config.number_of_jumps = (
            values.get("number_of_jumps") if "number_of_jumps" in visible_names else None
        )
        config.test_length = (
            values.get("test_length") if "test_length" in visible_names else None
        )

        config.starting_foot = values.get("starting_foot", "Not defined")

        # 滤波参数: 始终赋值
        config.min_contact_time = values.get("min_contact_time", 60)
        config.min_flight_time = values.get("min_flight_time", 0)
        config.max_flight_time = values.get("max_flight_time", 0)

        # 可选参数
        config.metronome_enabled = values.get("metronome_enabled", False)
        config.metronome_bpm = (
            values.get("metronome_bpm", 120) if config.metronome_enabled else 120
        )

        return config

    def set_config(self, config: AnyTestConfig) -> None:
        """从 TestConfig 反向填充控件值。用于加载历史配置。"""
        mapping = config.to_dict()

        for name, widget in self._widgets.items():
            val = mapping.get(name)
            if val is None:
                continue

            if isinstance(widget, QComboBox):
                idx = widget.findText(str(val))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            elif isinstance(widget, MSpinBox):
                widget.setValue(int(val))
            elif isinstance(widget, MTimeEdit):
                # val 格式 "mm:ss"
                parts = str(val).split(":")
                if len(parts) == 2:
                    widget.setTime(QTime(0, int(parts[0]), int(parts[1])))
            elif isinstance(widget, MSwitch):
                widget.setChecked(bool(val))

        self._refresh_visibility()

    def set_enabled(self, enabled: bool) -> None:
        """锁定/解锁面板。测试运行中调用 set_enabled(False)。"""
        for widget in self._widgets.values():
            widget.setEnabled(enabled)

    # ==================================================================
    #  UI 构建
    # ==================================================================

    def _build_ui(self):
        """构建完整面板 UI: Layer1 + Layer2(网格) + Layer3(折叠) + Layer4(折叠)。"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # ===== 基础配置 =====
        main_layout.addWidget(MDivider("基础配置"))

        # 测试模式：独占整行
        test_type_combo = self._create_enum_widget("test_type")
        row = self._create_form_row("测试模式", test_type_combo)
        main_layout.addWidget(row)

        # Layer2 参数：2 列网格
        self._basic_grid = QGridLayout()
        self._basic_grid.setSpacing(10)
        self._basic_grid_pos = 0  # 当前插入位置

        for param_name in self._LAYER2_PARAMS:
            param_def = self._schema.get_param_def(param_name)
            if param_def is None:
                continue
            applicable_params = self._schema.get_params_for_test(self._test_type)
            applicable_names = {p.name for p in applicable_params}
            if param_name not in applicable_names:
                continue

            widget = self._create_widget_for_param(param_name, param_def)
            if widget is None:
                continue

            display = param_def.display_name.split(" ")[0] if param_def.display_name else param_name
            card = self._create_form_row(display, widget)
            self._rows[param_name] = card
            r, c = divmod(self._basic_grid_pos, 2)
            self._basic_grid.addWidget(card, r, c)
            self._basic_grid_pos += 1

        main_layout.addLayout(self._basic_grid)

        # ===== Layer 3: 滤波参数 (折叠, 2 列网格) =====
        filter_container = QWidget()
        filter_grid = QGridLayout(filter_container)
        filter_grid.setContentsMargins(4, 4, 4, 4)
        filter_grid.setSpacing(10)
        pos = 0

        for param_name in self._LAYER3_PARAMS:
            param_def = self._schema.get_param_def(param_name)
            if param_def is None:
                continue

            widget = self._create_int_widget(param_name, param_def)
            display = param_def.display_name.split(" ")[0] if param_def.display_name else param_name
            unit_text = f" ({param_def.unit})" if param_def.unit else ""
            card = self._create_form_row(display + unit_text, widget)
            r, c = divmod(pos, 2)
            filter_grid.addWidget(card, r, c)
            pos += 1

        self._filter_section = MSectionItem(
            title="滤波参数", widget=filter_container, expand=False
        )
        main_layout.addWidget(self._filter_section)

        # ===== Layer 4: 可选参数 (折叠, 2 列网格) =====
        optional_container = QWidget()
        optional_grid = QGridLayout(optional_container)
        optional_grid.setContentsMargins(4, 4, 4, 4)
        optional_grid.setSpacing(10)

        # 节拍器开关
        metro_switch = self._create_switch_widget()
        row_metro = self._create_form_row("节拍器", metro_switch)
        self._widgets["metronome_enabled"] = metro_switch
        self._rows["metronome_enabled"] = row_metro
        optional_grid.addWidget(row_metro, 0, 0)

        # 节拍 BPM
        bpm_def = self._schema.get_param_def("metronome_bpm")
        bpm_spinbox = self._create_int_widget("metronome_bpm", bpm_def)
        row_bpm = self._create_form_row("节拍 BPM", bpm_spinbox)
        optional_grid.addWidget(row_bpm, 0, 1)

        self._optional_section = MSectionItem(
            title="可选参数", widget=optional_container, expand=False
        )
        main_layout.addWidget(self._optional_section)

        # ===== 弹性空间 =====
        main_layout.addStretch()

    def _create_form_row(self, label_text: str, widget: QWidget) -> QWidget:
        """创建 FormRow: 卡片风格，标签在上、控件在下。"""
        row = QWidget()
        row.setStyleSheet(
            "QWidget { "
            "  background-color: rgba(45, 45, 50, 0.7); "
            "  border-radius: 8px; "
            "}"
        )

        layout = QVBoxLayout(row)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(4)

        label = MLabel(label_text)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        label.setStyleSheet(
            "font-size: 11pt; color: #999999; "
            "background: transparent; border: none;"
        )

        # 控件字号增大
        widget.setStyleSheet(
            widget.styleSheet() + """
            font-size: 13pt;
            min-height: 32px;
            """
        )

        layout.addWidget(label)
        layout.addWidget(widget)

        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.setMinimumHeight(68)
        return row

    def _create_widget_for_param(self, param_name: str, param_def: ParamDef) -> QWidget | None:
        """根据参数类型分派创建对应的控件。"""
        if param_def.param_type == "enum":
            widget = self._create_enum_widget(param_name)
        elif param_def.param_type == "integer":
            widget = self._create_int_widget(param_name, param_def)
        elif param_def.param_type == "string" and param_name == "test_length":
            widget = self._create_time_widget()
        else:
            return None  # 不支持的类型

        self._widgets[param_name] = widget
        return widget

    def _create_enum_widget(self, param_name: str) -> QComboBox:
        """为枚举参数创建 QComboBox，选项从 schema 获取。"""
        combo = QComboBox()
        values = self._schema.get_enum_values(param_name, self._test_type)
        combo.addItems(values)

        # 设置默认值
        param_def = self._schema.get_param_def(param_name)
        if param_def and param_def.default:
            idx = combo.findText(str(param_def.default))
            if idx >= 0:
                combo.setCurrentIndex(idx)

        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 存入 _widgets（test_type 在 _build_ui 中单独处理）
        self._widgets[param_name] = combo
        return combo

    def _create_int_widget(self, param_name: str, param_def: ParamDef | None) -> MSpinBox:
        """为整数参数创建 MSpinBox，范围和默认值从 ParamDef 读取。"""
        spinbox = MSpinBox()
        spinbox.setKeyboardTracking(False)  # 避免键盘输入中间态触发 valueChanged

        # 解析范围
        lo, hi = 0, 9999
        if param_def and param_def.range_str and not param_def.range_str.startswith("{"):
            parts = param_def.range_str.split("-")
            if len(parts) == 2:
                try:
                    lo, hi = int(parts[0]), int(parts[1])
                except ValueError:
                    pass
        spinbox.setRange(lo, hi)

        # 设置默认值
        if param_def and param_def.default is not None:
            try:
                spinbox.setValue(int(param_def.default))
            except (ValueError, TypeError):
                pass

        spinbox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._widgets[param_name] = spinbox
        return spinbox

    def _create_time_widget(self) -> MTimeEdit:
        """为 test_length 创建 MTimeEdit，格式 mm:ss。"""
        time_edit = MTimeEdit()
        time_edit.setDisplayFormat("mm:ss")
        time_edit.setTime(QTime(0, 1, 0))  # 默认 01:00

        time_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._widgets["test_length"] = time_edit
        return time_edit

    def _create_switch_widget(self) -> MSwitch:
        """为布尔参数创建 MSwitch。"""
        switch = MSwitch()
        switch.setChecked(False)
        return switch

    # ==================================================================
    #  联动逻辑
    # ==================================================================

    def _on_stop_type_changed(self, text: str) -> None:
        """stop_type 变更 → 刷新条件字段的 show/hide。"""
        current_vals = self._current_values()
        current_vals["stop_type"] = text  # 确保用最新值

        visible_params = self._schema.get_visible_params(self._test_type, current_vals)
        visible_names = {p.name for p in visible_params}

        for field_name in self._CONDITIONAL_FIELDS:
            if field_name in self._rows:
                if field_name in visible_names:
                    self._rows[field_name].show()
                else:
                    self._rows[field_name].hide()

        self.config_changed.emit()

    def _on_metronome_changed(self, checked: bool) -> None:
        """metronome_enabled 变更 → metronome_bpm 行的 show/hide。"""
        if "metronome_bpm" in self._rows:
            if checked:
                self._rows["metronome_bpm"].show()
            else:
                self._rows["metronome_bpm"].hide()

        self.config_changed.emit()

    def _refresh_visibility(self) -> None:
        """根据当前值刷新所有条件字段显隐。初始化和 test_type 切换时调用。"""
        # 1. stop_type 联动
        stop_type = ""
        if "stop_type" in self._widgets:
            w = self._widgets["stop_type"]
            if isinstance(w, QComboBox):
                stop_type = w.currentText()
        self._on_stop_type_changed(stop_type)

        # 2. metronome 联动
        metro_on = False
        if "metronome_enabled" in self._widgets:
            w = self._widgets["metronome_enabled"]
            if isinstance(w, MSwitch):
                metro_on = w.isChecked()
        self._on_metronome_changed(metro_on)

    def _connect_signals(self) -> None:
        """连接所有联动信号和 config_changed 统一通知。"""
        # 1. stop_type 联动
        if "stop_type" in self._widgets:
            w = self._widgets["stop_type"]
            if isinstance(w, QComboBox):
                w.currentTextChanged.connect(self._on_stop_type_changed)

        # 2. metronome 联动
        if "metronome_enabled" in self._widgets:
            w = self._widgets["metronome_enabled"]
            if isinstance(w, MSwitch):
                w.toggled.connect(self._on_metronome_changed)

        # 3. 所有控件 → config_changed 统一通知
        for name, widget in self._widgets.items():
            if isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(lambda _: self.config_changed.emit())
            elif isinstance(widget, MSpinBox):
                widget.valueChanged.connect(lambda _: self.config_changed.emit())
            elif isinstance(widget, MTimeEdit):
                widget.timeChanged.connect(lambda _: self.config_changed.emit())
            elif isinstance(widget, MSwitch):
                # MSwitch.toggled 已在 metronome 联动中连接，
                # 但也需要统一发 config_changed
                widget.toggled.connect(lambda _: self.config_changed.emit())

    # ==================================================================
    #  值收集
    # ==================================================================

    def _current_values(self) -> dict:
        """收集所有控件当前值为 dict。"""
        result = {}
        for name, widget in self._widgets.items():
            if isinstance(widget, QComboBox):
                result[name] = widget.currentText()
            elif isinstance(widget, MSpinBox):
                result[name] = widget.value()
            elif isinstance(widget, MTimeEdit):
                t = widget.time()
                result[name] = t.toString("mm:ss") if t.isValid() else "00:00"
            elif isinstance(widget, MSwitch):
                result[name] = widget.isChecked()
        return result
