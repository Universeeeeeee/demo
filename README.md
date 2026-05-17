# Iron_Jump — Agent Onboarding Guide

> **读者**: AI coding agent。本文档旨在让你在最短时间内理解项目的架构、约束和当前状态，避免犯已经讨论过的错误。

## 项目本质

这是一个 **OptoJump 兼容的步态/纵跳分析系统**。硬件是两根分别放置在两侧的条形装置，每根包含 96 个红外 LED，通过 USB 连接 PC，以 1000Hz 采样率实时上报每个 LED 的遮挡状态。软件侧负责：接收原始数据 → 算法检测触地/腾空事件 → UI 实时展示 → 生成测试报告。

### ⚠️ 当前范围与扩展性规划

**当前硬件**: 仅一对一米段条形装置（每根 96 个红外 LED），所有模块（hardware / engine / ui / agent）均在此前提下开发。

**未来测试类型**: 纵跳（Jump Test）只是第一个完成的测试类型，目的是 **建立一套完整的范式**（参数配置 → 数据采集 → 实时分析 → 报告生成），方便后续扩展到步态分析、短跑、跑步机测试等更多类型。修改或新增代码时，应确保设计不硬编码于纵跳场景，而是遵循 `TestConfig.test_type` 分发的通用模式。

**未来硬件**: 将支持多米段设备级联（多对条形装置串联，LED 数量从 96 扩展到 N×96）。因此，当前模块中涉及 LED 数量、空间坐标、聚类算法的部分，**必须确保可扩展性**——避免硬编码 96 或单段假设。修改 `hardware/`、`engine/` 层代码时尤其注意这一点。

## 技术栈

| 层 | 技术 | 关键约束 |
|:---|:---|:---|
| **UI** | PySide2 + qtpy + dayu_widgets (本地库) | dayu_widgets 是本地安装的第三方库，已被 .gitignore 排除 |
| **图表** | pyqtgraph (可选，降级为 QLabel 占位) | `_PG_AVAILABLE` 检查 |
| **硬件通信** | ctypes + CyUsbInterface.dll (stdcall) | Windows-only, DLL 在 `hardware/` 目录下 |
| **AI Agent** | pydantic-ai + DeepSeek LLM | .env 中配置 OPENAI_BASE_URL 和 API_KEY |
| **数据导出** | openpyxl (Excel) | — |

**采样率固定 1000Hz** — 这是硬件约束，代码中不应出现采样率可配置的逻辑。

## 目录结构与各模块职责

```
Iron_Jump/
├── hardware/               # L1 层：硬件通信（不要修改）
│   ├── CyUsbInterface.dll  # Cypress USB 驱动 DLL
│   ├── protocol.py         # 协议解析器（帧头帧尾、CRC8、分包重组）
│   ├── receive.py          # DLL ctypes 封装 + CyUsbInterfaceDevice 高级封装
│   └── usb_worker.py       # QObject Worker，管理 USB 读取线程，发射 Qt Signal
│
├── engine/                 # L2 层：算法引擎（不要修改，除非修复 bug）
│   ├── gait_engine.py      # 核心引擎：接收原始帧 → 检测事件 → 发射高级信号
│   ├── single_foot_tracker.py  # 纵跳模式：单足触地/腾空状态机
│   ├── contact_tracker.py  # 步态模式：基于接触区域的步态事件追踪
│   ├── spatial_clusterer.py # 空间聚类：将 96 位数据聚类为脚印
│   └── extra_parameter.py  # 高阶步态参数计算（步长、步速等）
│
├── config/                 # 配置层
│   ├── Iron_parameters.json # OptoJump 参数定义（4 层结构，含联动规则）
│   ├── param_schema.py     # JSON Schema 加载器 + 校验器
│   ├── test_config.py      # TestConfig dataclass：一次测试的完整运行时参数
│   └── test_report.py      # TestReport frozen dataclass：不可变测试结果快照
│
├── agent/                  # AI Agent 模块
│   ├── models.py           # AthleteProfile(输入) + LLMTestConfig + ChatResponse(LLM 输出)
│   ├── rule_engine.py      # 离线：规则引擎，保守聚合 + 顺序无关 → TestConfig
│   ├── llm_agent.py        # 在线：Pydantic AI + DeepSeek + ClarifyGPT 验证 → TestConfig
│   ├── gait_agent.py       # Facade 门面，统一两种模式对外接口 + 生命周期管理
│   └── agent_test_ui.py    # Agent 独立测试窗口（不依赖硬件）
│
├── ui/                     # UI 层
│   ├── main_window.py      # 入口：多视图路由 (QStackedWidget)
│   ├── session_controller.py # 会话控制器：管理 QThread + UsbWorker + GaitEngine 生命周期
│   ├── param_panel.py      # 动态参数配置面板（Schema 驱动）
│   ├── data_show.py        # 旧版单页 Demo（保留为回退方案，不要删除）
│   ├── camera.py           # OpenCV 相机（独立线程，独立窗口）
│   ├── led_con.py / led_panel.py  # LED 状态可视化
│   └── views/
│       ├── setup_view.py      # 配置页：ParamPanel + "准备就绪"按钮
│       ├── execution_view.py  # 执行页：MetricCard 仪表盘 + 实时图表
│       └── report_view.py     # 报告页：统计汇总 + Excel 导出
│
├── tests/                  # 单元测试
│   ├── test_rule_engine.py     # 规则引擎 14 个测试（保守聚合/边界值/顺序无关）
│   └── test_llm_test_config.py # LLMTestConfig 转换 5 个测试（字段传递/reply_message 泄漏）
├── path_utils.py           # DLL 路径查找工具
├── claude.md               # 代码编写行为准则（必读）
├── .env                    # DeepSeek API 配置
└── requirements.txt        # Python 依赖
```

## 核心架构：信号流

```
用户点击"准备就绪"
  → SetupView.ready_signal.emit(TestConfig)
  → MainWindow._on_ready(config)
      → ExecutionView.reset() + configure(config)
      → SessionController.prepare(config)
          → 创建 QThread + UsbWorker + GaitEngine
          → moveToThread
          → 连接信号: L1→L2 (DirectConnection), L2→Controller (QueuedConnection)
      → 切到 ExecutionView

用户点击"开始"
  → SessionController.start() → thread.start()

实时数据流 (后台线程 → 主线程):
  UsbWorker.raw_contact_signal
    →[DirectConnection]→ GaitEngine.process_raw_frame()
    →[产生事件]→ hop_event / gait_step_event
    →[QueuedConnection]→ SessionController → ExecutionView

测试结束 (自动/手动):
  GaitEngine.test_finished.emit(reason)
  → SessionController._on_engine_finished()
      → 200ms 延迟 → stop()
      → build_report(engine, reason) → TestReport (frozen dataclass)
      → session_finished.emit(TestReport)
  → MainWindow → ReportView.load_report(report)
```

## 线程模型

```
┌─────────────────────────────────────────────┐
│ 主线程 (GUI)                                  │
│  MainWindow, SetupView, ExecutionView,       │
│  ReportView, SessionController               │
│  (所有 Qt Widget 操作必须在此线程)              │
└──────────────┬──────────────────────────────┘
               │ QueuedConnection (低频 ~2-5Hz)
┌──────────────▼──────────────────────────────┐
│ Worker 线程 (QThread)                         │
│  UsbWorker → GaitEngine                      │
│  DirectConnection (高频 1000Hz)               │
│  [USB 读取在 daemon 子线程，回调到此线程]        │
└─────────────────────────────────────────────┘
```

**关键约束**:
- GaitEngine 不能 import 任何 QtWidgets
- 所有 UI 更新必须通过 QueuedConnection 回到主线程
- `SessionController.prepare()` 中严格遵循: 创建对象 → moveToThread → 连接信号 → start

## 参数配置系统

参数配置有 3 种方式，输出完全一致的 `TestConfig`:

| 方式 | 入口 | 说明 |
|:---|:---|:---|
| **手动配置** | `ParamPanel.get_config()` | Schema 驱动的动态表单 |
| **规则引擎** (离线) | `GaitAgent.configure_offline()` | 按 AthleteProfile 自动推荐 |
| **LLM** (在线) | `GaitAgent.chat_online()` | 自然语言对话 → 结构化输出 |

### 参数分层 (来自 Iron_parameters.json)

| Layer | 内容 | 示例 |
|:---|:---|:---|
| 1 | 测试类型选择 | test_macro_type, test_type |
| 2 | 主配置参数 | stop_type, number_of_jumps, test_length |
| 3 | 滤波参数 | min_contact_time, min_flight_time, max_flight_time |
| 4 | 可选反馈 | metronome_enabled, metronome_bpm |

### 参数联动规则

- `stop_type = "Status change"` 时: `number_of_jumps` 和 `finish_position` 可见
- `stop_type = "End of Time"` 时: `test_length` 可见
- `stop_type = "External impulse"` 时: 硬件层未实现，UI 选项保留但功能不可用
- `visibility_condition` 可能是 per-test-type 格式（嵌套 dict）

## 关键设计决策（已确认，不要推翻）

| 决策 | 结论 | 原因 |
|:---|:---|:---|
| **采样率** | 固定 1000Hz | 硬件约束 |
| **TestConfig** | dataclass, 不改为 BaseModel | 全系统通用 (engine/ui/controller)，改动影响面太大 |
| **LLM 输出** | 新增 `LLMTestConfig(BaseModel)` 作为转换层 | 通过 Field/Literal 编码约束进 JSON Schema，提升 LLM 输出准确率 |
| **TestReport** | frozen=True dataclass | ReportView 不持有 GaitEngine 引用 |
| **旧 data_show.py** | 保留不动 | 回退方案 |
| **Camera** | 独立 OpenCV 窗口 | 不嵌入 Qt |
| **L1/L2 层** | 不动 usb_worker.py / gait_engine.py | 除非修复 bug |
| **dayu_widgets** | 本地库，.gitignore 已排除 | 不要提交到 Git |

## Agent 模块设计

### 架构

```
用户/UI
  ↓
GaitAgent (Facade)
  ├── 离线: RuleEngine.configure(test_type, AthleteProfile) → TestConfig
  └── 在线: LLMConfigAgent.chat(user_msg, AthleteProfile)
              → asyncio.run(_flow())
                → agent.run() → Union[LLMTestConfig, ChatResponse]
                  ├── ChatResponse → 自然语言追问/解释
                  └── LLMTestConfig → _verify_config()
                       → asyncio.gather() 并行验证
                       → .to_test_config() → TestConfig
```

### LLM 结构化输出层

`LLMTestConfig(BaseModel)` 是专为 Pydantic AI 设计的中间层：

```
LLM 输出 JSON → Pydantic 校验 → LLMTestConfig (BaseModel)
  → .to_test_config() → TestConfig (dataclass, 系统通用)
  → ParamSchema.validate() → 业务逻辑二次校验
```

**为什么不直接用 TestConfig？** TestConfig 是 dataclass，生成的 JSON Schema 只有字段名和类型，LLM 看不到枚举值、数值范围、字段含义。LLMTestConfig 通过 `Field(description=..., ge=..., le=...)` 和 `Literal[...]` 将这些约束编码进 schema，让 LLM 输出更准确。

**格式归一化**：`@field_validator("test_length")` 将 LLM 可能输出的 `"2m"`、`"120s"` 等格式自动转为 `"02:00"` (mm:ss)。

### 其他关键实现细节

- **RuleEngine**: `PROFILE_RULES` 是 `list[tuple[Callable, dict]]`，数据驱动。多规则命中同一字段时取最保守值（`min_contact→MAX`, `number_of_jumps→MIN`, `max_flight→MIN(非零)`），与规则添加顺序无关。14 个单元测试覆盖
- **LLMConfigAgent**: 延迟初始化 (`_ensure_agent()`) + 预热 (`warmup()`)，避免导入崩溃，首次对话不卡。chat() 同步接口，内部 `asyncio.run()` 统一事件循环以支持并行验证
- **三层校验**: ① Pydantic BaseModel 校验结构+范围+枚举 → ② `.to_test_config()` 转换 → ③ ParamSchema 校验跨字段联动

### ClarifyGPT 模式 (已实现)

借鉴 ClarifyGPT (ACM FSE 2024) 的 "Detect → Clarify → Refine" 思想:
1. **多次采样**: LLM 独立生成 N 份配置 (N_SAMPLES=3)。`_verify_config()` 用 `asyncio.gather()` 并行，配置生成 ~21s→~14s
2. **代码做裁判**: `_find_disagreements()` 对比关键字段，不一致 = 有歧义
3. **模型做分析**: `_generate_clarification()` 将分歧翻译成人话追问
4. **独立采样**: 每次采样使用相同的 `message_history` 快照，不互相干扰
5. **追问能力**: `Union[LLMTestConfig, ChatResponse]` 让 LLM 自主选择输出类型。信息不足时退回 ChatResponse 追问，不再硬猜配置

## 开发环境

```bash
# 安装依赖
pip install -r requirements.txt

# 启动主界面
python ui/main_window.py

# 启动旧版 Demo（回退验证）
python ui/data_show.py

# 启动 Agent 测试 UI（不需要硬件）
python agent/agent_test_ui.py

# 直接测试 USB 通信
python hardware/receive.py

# 验证 import 链
python -c "from agent import GaitAgent, AthleteProfile; print('OK')"
python -c "from ui.main_window import MainWindow; print('OK')"
```

### 环境变量

| 变量 | 默认值 | 说明 |
|:---|:---|:---|
| `DAYU_DLL` | 自动查找 | DLL 路径覆盖 |
| `DAYU_VID` | 0x04B4 | USB Vendor ID |
| `DAYU_PID` | 0x1004 | USB Product ID |
| `DAYU_TIMEOUT` | 30 | USB 读取超时 (ms) |
| `DAYU_CHUNK` | 512 | USB 读取块大小 |
| `DAYU_TARGET_RATE_HZ` | 200 | UI LED 信号刷新率 |
| `DAYU_LOG_INTERVAL_MS` | 100 | 日志节流间隔 |
| `OPENAI_BASE_URL` | (from .env) | LLM API 地址 |
| `OPENAI_API_KEY` | (from .env) | LLM API Key |

## 当前开发状态

| 模块 | 状态 | 说明 |
|:---|:---|:---|
| hardware/ (L1) | ✅ 稳定 | 仅支持 LED 光栅数据，不支持 Jack 口 / Status change 信号 |
| engine/ (L2) | ✅ 稳定 | 纵跳 + 步态双模式，自动停止已实现 |
| config/ | ✅ 稳定 | TestConfig + ParamSchema + TestReport 完整 |
| ui/ 多视图 | ✅ 基本完成 | Setup → Execution → Report 工作流 |
| ui/data_show.py | 🔒 保留 | 旧版回退方案 |
| agent/ 规则引擎 | ✅ 完成 | 4 条规则，保守聚合 + 顺序无关，14 个单元测试 |
| agent/ LLMTestConfig | ✅ 完成 | BaseModel 转换层 + @field_validator，5 个单元测试 |
| agent/ LLM 在线模式 | ✅ 已验证 | DeepSeek API 实际调用通过，P0-P2 性能优化落地 |
| agent/ ClarifyGPT | ✅ 已实现 | 并行采样 + 一致性检查 + 追问生成 |
| Agent 集成到主 UI | 📋 待开发 | `agent_test_ui.py` → `SetupView` |
| LED Panel 集成 | 📋 Phase 6 | 未来迭代 |
| Camera 嵌入 Qt | 📋 Phase 6 | 未来迭代 |

## 常见陷阱

1. **不要在 GaitEngine 中 import QtWidgets** — 它在 Worker 线程中运行
2. **不要假设采样率可配置** — 固定 1000Hz
3. **不要删除 data_show.py** — 它是回退方案
4. **不要让 ReportView 持有 GaitEngine 引用** — 通过 TestReport (frozen) 传递
5. **不要在模块导入时初始化 LLM** — 使用延迟初始化
6. **不要提交 dayu_widgets/ 到 Git** — 它是本地第三方库
7. **不要把 TestConfig 改为 BaseModel** — LLM 输出用 `LLMTestConfig(BaseModel)` 转换层，系统通用配置保持 dataclass
8. **stop() 必须在 build_report() 之前停线程** — 否则竞态
9. **SessionController.prepare() 中信号连接顺序很重要** — 先 moveToThread，再连接
10. **ParamSchema.validate() 会检查 Layer 1 参数** — agent 调用时需补充 test_macro_type

## 编码规范

参见 `claude.md`。核心原则:
- **先想后写** — 不确定就问
- **最小改动** — 不 "改进" 无关代码
- **简洁优先** — 200 行能用 50 行就用 50 行
- **可验证** — 每步都有明确的成功标准
