# Iron_Jump 系统架构文档

> 最后更新: 2026-05-19

## 1. 项目概述

OptoJump 兼容的步态/纵跳分析系统。硬件是两根分别放置在两侧的条形装置，每根包含 96 个红外 LED，通过 USB 连接 PC，以 1000Hz 采样率实时上报每个 LED 的遮挡状态。

软件负责：接收原始数据 → 算法检测触地/腾空事件 → UI 实时展示 → 生成测试报告。

## 2. 技术栈

| 层 | 技术 | 说明 |
|:---|:---|:---|
| **语言** | Python 3.11 | 统一环境，不再分 dayu / pydantic_ai 两个 conda 环境 |
| **UI** | PySide6 6.11 + qtpy + dayu_widgets | dayu_widgets 为纯 Python 库，本地源码放在项目根 |
| **图表** | pyqtgraph (可选) | 降级为 QLabel 占位（`_PG_AVAILABLE` 检查） |
| **硬件通信** | ctypes + CyUsbInterface.dll (stdcall) | Windows-only |
| **AI Agent** | pydantic-ai + DeepSeek v4-flash | 通过 .env 配置 API 地址和密钥 |
| **数据导出** | openpyxl (Excel) | |
| **数据持久化** | SQLite (内置 sqlite3) | 受试者管理 + 测试记录 |
| **相机** | OpenCV + OBSBOT SDK (ctypes) | DirectShow 后端，独立窗口 |

**采样率固定 1000Hz** — 硬件约束，代码中不应出现采样率可配置的逻辑。

## 3. 目录结构

```
Iron_Jump/
├── hardware/                 # L1 层：硬件通信
│   ├── CyUsbInterface.dll    # Cypress USB 驱动 DLL
│   ├── protocol.py           # 协议解析器（帧头帧尾、CRC8、分包重组）
│   ├── receive.py            # DLL ctypes 封装
│   └── usb_worker.py         # QObject Worker，管理 USB 读取线程，发射 Qt Signal

├── engine/                   # L2 层：算法引擎
│   ├── gait_engine.py        # 核心引擎：接收原始帧 → 检测事件 → 发射高级信号
│   ├── single_foot_tracker.py  # 纵跳模式：单足触地/腾空状态机
│   ├── contact_tracker.py    # 步态模式：基于接触区域的步态事件追踪
│   ├── spatial_clusterer.py  # 空间聚类：将 96 位数据聚类为脚印
│   └── extra_parameter.py    # 高阶步态参数计算（步长、步速等）

├── config/                   # 配置层
│   ├── Iron_parameters.json  # OptoJump 参数定义（4 层结构，含联动规则）
│   ├── param_schema.py       # JSON Schema 加载器 + 校验器
│   ├── test_config.py        # TestConfig dataclass：一次测试的完整运行时参数
│   └── test_report.py        # TestReport frozen dataclass：不可变测试结果快照

├── data/                     # 数据持久化层
│   └── subject_store.py      # SQLite 受试者管理：创建/搜索/历史记录/Session 归档

├── agent/                    # AI Agent 模块
│   ├── models.py             # AthleteProfile(输入) + LLMTestConfig + ChatResponse
│   ├── rule_engine.py        # 离线模式：规则引擎 → TestConfig
│   ├── llm_agent.py          # 在线模式：LLMConfigAgent (Fast Gate + Parallel Clarify)
│   ├── gait_agent.py         # Facade 门面，统一两种模式对外接口 + 生命周期管理
│   └── agent_test_ui.py      # Agent 独立测试窗口（不依赖硬件）

├── ui/                       # UI 层
│   ├── main_window.py        # 入口：多视图路由 (QStackedWidget)
│   ├── session_controller.py # 会话控制器：管理 QThread + UsbWorker + GaitEngine 生命周期
│   ├── param_panel.py        # 动态参数配置面板（Schema 驱动）
│   ├── camera.py             # OpenCV 相机（独立线程，独立窗口）
│   ├── led_con.py            # LED 状态可视化
│   ├── led_panel.py          # LED 面板组件
│   ├── data_show.py          # 旧版单页 Demo（回退方案）
│   └── views/
│       ├── setup_view.py         # 配置页：ParamPanel + AgentConfigPanel + 受试者选择
│       ├── agent_config_panel.py # Agent 智能配置面板（在线 LLM / 离线规则引擎）
│       ├── execution_view.py     # 执行页：MetricCard 仪表盘 + 实时图表
│       └── report_view.py        # 报告页：统计汇总 + Excel 导出

├── camera/                   # 相机模块
│   ├── logi_camera.py        # 通用 USB 摄像头 (OpenCV MSMF)
│   ├── tinyse_camera.py      # OBSBOT Tiny SE 摄像头 (DirectShow + SDK 控制)
│   └── tinyse_dshow_capture.py  # DirectShow 采集 DLL 封装

├── tests/
│   ├── test_rule_engine.py     # 规则引擎 14 个测试
│   ├── test_llm_test_config.py # LLMTestConfig 转换 5 个测试
│   └── test_subject_store.py   # SubjectStore 7 个测试

├── docs/
│   └── architecture.md       # 本文档
├── path_utils.py             # DLL 路径查找工具
├── CLAUDE.md                 # 代码编写行为准则
├── plan.md                   # 开发计划
├── .env                      # DeepSeek API 配置
└── requirements.txt          # Python 依赖
```

## 4. 分层架构

```
┌─────────────────────────────────────────┐
│ UI 层 (Qt)                               │
│  main_window.py → views/                 │
│  session_controller.py                   │
├─────────────────────────────────────────┤
│ Agent 层                                 │
│  gate_agent.py (Facade)                  │
│  ├── llm_agent.py (在线: Fast Gate +     │
│  │   Parallel Clarify)                   │
│  └── rule_engine.py (离线: 规则引擎)      │
├─────────────────────────────────────────┤
│ 配置层                                   │
│  param_schema.py + test_config.py        │
├─────────────────────────────────────────┤
│ 算法引擎层 (L2)                           │
│  gait_engine.py + trackers               │
├─────────────────────────────────────────┤
│ 硬件通信层 (L1)                           │
│  usb_worker.py + protocol.py             │
├─────────────────────────────────────────┤
│ 数据持久化层                              │
│  subject_store.py (SQLite)               │
└─────────────────────────────────────────┘
```

**关键约束**:
- GaitEngine 不 import 任何 QtWidgets — 在 Worker 线程中运行
- 所有 UI 更新通过 QueuedConnection 回到主线程
- UI 层不直接 import agent（AgentConfigPanel 通过 gait_agent Facade 访问）

## 5. 核心信号流

### 5.1 测试生命周期

```
用户点击"准备就绪"
  → SetupView.ready_signal.emit(SessionSetup)
  → MainWindow._on_ready(setup)
      → ExecutionView.reset() + configure(config)
      → SessionController.prepare(config)
          → 创建 QThread + UsbWorker + GaitEngine
          → moveToThread
          → 连接信号: L1→L2 (DirectConnection), L2→Controller (QueuedConnection)
      → 切到 ExecutionView

用户点击"开始"
  → ExecutionView.start_requested
  → SessionController.start() → thread.start()
```

### 5.2 实时数据流

```
后台线程:
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
      → SubjectStore.record_session() 归档
```

### 5.3 受试者选择与配置回填

```
SetupView 受试者搜索/选择
  → _refresh_subject_results(query)
  → SubjectStore.search_subjects()

"加载上次参数"
  → SubjectStore.get_last_session(subject_id)
  → param_panel.set_config(session.config)

Agent 生成配置 (AgentConfigPanel)
  → config_selected(TestConfig)
  → param_panel.set_config(config)
  → _update_summary()
```

## 6. 线程模型

```
┌─────────────────────────────────────────────┐
│ 主线程 (GUI)                                  │
│  MainWindow, SetupView, ExecutionView,        │
│  ReportView, SessionController                │
│  (所有 Qt Widget 操作必须在此线程)              │
└──────────────┬──────────────────────────────┘
               │ QueuedConnection (低频 ~2-5Hz)
┌──────────────▼──────────────────────────────┐
│ Worker 线程 (QThread)                         │
│  UsbWorker → GaitEngine                      │
│  DirectConnection (高频 1000Hz)               │
│  [USB 读取在 daemon 子线程，回调到此线程]        │
└─────────────────────────────────────────────┘

Agent LLM 调用线程 (QThread):
  WarmupWorker → warmup_online()
  LLMWorker → chat_online_stream()
```

**关键约束**:
- `SessionController.prepare()` 中严格遵循: 创建对象 → moveToThread → 连接信号 → start
- `stop()` 必须在 `build_report()` 之前停线程，否则竞态

## 7. 参数配置系统

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

- `stop_type = "Status change"` → `number_of_jumps` 和 `finish_position` 可见
- `stop_type = "End of Time"` → `test_length` 可见
- `stop_type = "External impulse"` → 手动停止，硬件层未实现

### 术语说明

项目中"参数"一词有四种不同含义，代码和文档使用以下对照关系：

| 中文术语 | 代码类型 | 含义 |
|:---|:---|:---|
| 配置参数 | `TestConfig` | 测试前由用户或系统设定，参与采集、停止、过滤、计算 |
| 会话元数据 | `SessionMetadata` | 测试开始时冻结的受试者或环境信息，不一定是算法阈值 |
| 结果参数 | `ResultMetric` | 测试后从事件和配置计算出的逐步或逐周期结果 |
| 汇总统计 | `MetricSummary` | 对结果参数做 min/max/mean/std/CV、左右脚、不对称性统计 |

数据库中的配置快照称为"配置快照"，报告快照称为"报告快照"。

## 8. Agent 模块设计

### 8.1 整体架构

```
用户/UI
  ↓
GaitAgent (Facade)
  ├── 离线: RuleEngine.configure(test_type, AthleteProfile) → TestConfig
  └── 在线: LLMConfigAgent.chat(user_msg, AthleteProfile)
            → asyncio.run(_flow())
              ├── _is_config_request() 关键词 gate
              │     ├── 非配置 → 单次 agent.run() → ChatResponse
              │     └── 配置 → _run_parallel_clarify()
              │           → 3 次 agent.run() 真正并行 (同一快照)
              │           → _resolve_parallel_samples() 聚类裁判
              │           → .to_test_config() → TestConfig
```

### 8.2 Fast Gate + Parallel Clarify

**Fast Gate**：确定性关键词检测（`_is_config_request()`），三级词表（强配置短语 / 动作词 / 约束词）。闲聊"你好"、参数解释等不触发并行，走单次 LLM。

**Parallel Clarify**：命中 gate 后，从同一个 `message_history` 快照并行发起 3 次 `agent.run()`，所有 sample 地位平等。用 `_cluster_configs()` 按关键字段值聚类：
- 1 组一致 → 随机选代表，转 TestConfig，校验通过后输出
- 多组分歧 → `_find_disagreements()` + `_generate_clarification()` 追问
- 有效配置不足 2 个 → 追问，请用户补充信息

**History 更新策略**：
- 非配置路径：使用该次调用的 `result.all_messages()`
- 配置成功：使用被选中代表 sample 的 `result.all_messages()`
- 分歧/不足：使用第一个 ChatResponse 的 history，否则用第一个 sample

**Warmup**：`warmup()` 发送真实 API 请求预热 TCP/TLS 连接和服务端 GPU 实例，在后台线程执行，不阻塞 UI。

### 8.3 LLM 结构化输出层

```
LLM 输出 JSON → Pydantic 校验 → LLMTestConfig (BaseModel)
  → .to_test_config() → TestConfig (dataclass, 系统通用)
  → ParamSchema.validate() → 业务逻辑二次校验
```

`LLMTestConfig(BaseModel)` 是中间层：通过 `Field(description=..., ge=..., le=...)` 和 `Literal[...]` 将约束编码进 JSON Schema，让 LLM 输出更准确。`@field_validator("test_length")` 归一化 `"2m"`、`"120s"` 等格式为 `"02:00"`。

### 8.4 规则引擎

`PROFILE_RULES` 是 `list[tuple[Callable, dict]]`，数据驱动。多规则命中同一字段时取最保守值（`min_contact→MAX`, `number_of_jumps→MIN`, `max_flight→MIN(非零)`），与规则添加顺序无关。

## 9. 关键设计决策

| 决策 | 结论 | 原因 |
|:---|:---|:---|
| **采样率** | 固定 1000Hz | 硬件约束 |
| **TestConfig** | dataclass, 不改为 BaseModel | 全系统通用 (engine/ui/controller) |
| **LLM 输出** | 新增 `LLMTestConfig(BaseModel)` 转换层 | 不改 TestConfig，但给 LLM 更好的约束 |
| **TestReport** | frozen=True dataclass | ReportView 不持有 GaitEngine 引用 |
| **Python 版本** | 3.11 统一环境 | 消除 agent/ui 间的版本边界 |
| **Agent 集成方式** | AgentConfigPanel 嵌入 SetupView | 从 agent_test_ui 独立测试工具 → 主 UI 配置组件 |
| **LLM 调用模式** | Fast Gate + Parallel Clarify | 非配置请求不浪费并行采样，配置请求样本地位平等 |
| **相机** | 独立 OpenCV 窗口 | 不嵌入 Qt，预览控制链窗口生命周期内复用 |
| **旧 data_show.py** | 保留不动 | 回退方案 |
| **dayu_widgets** | 本地源码，.gitignore 排除 | 不提交到 Git |

## 10. 常见陷阱

1. **不要在 GaitEngine 中 import QtWidgets** — 在 Worker 线程中运行
2. **不要假设采样率可配置** — 固定 1000Hz
3. **不要删除 data_show.py** — 回退方案
4. **不要让 ReportView 持有 GaitEngine 引用** — 通过 TestReport (frozen) 传递
5. **不要在模块导入时初始化 LLM** — 使用延迟初始化 (`_ensure_agent()`)
6. **不要把 TestConfig 改为 BaseModel** — LLM 输出用 `LLMTestConfig` 转换层
7. **stop() 必须在 build_report() 之前停线程** — 否则竞态
8. **SessionController.prepare() 中信号连接顺序**: 先 moveToThread，再连接信号
9. **ParamSchema.validate() 会检查 Layer 1 参数** — agent 调用时需补充 test_macro_type
10. **camera 控制链 stop 后复用** — 只在 closeEvent 释放，Start/Stop 循环保持控制链存活