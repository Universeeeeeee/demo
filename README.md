# Iron_Jump — Agent Onboarding Guide

> **读者**: AI coding agent。本文档旨在让你在最短时间内理解项目的架构、约束和当前状态，避免犯已经讨论过的错误。

## 项目本质

这是一个 **OptoJump 兼容的步态/纵跳分析系统**。硬件是两根分别放置在两侧的条形装置，每根包含 96 个红外 LED，通过 USB 连接 PC，以 1000Hz 采样率实时上报每个 LED 的遮挡状态。软件侧负责：接收原始数据 → 算法检测触地/腾空事件 → UI 实时展示 → 生成测试报告。

### ⚠️ 当前范围与扩展性规划

**当前硬件**: 仅一对一米段条形装置（每根 96 个红外 LED），所有模块（hardware / engine / ui / agent）均在此前提下开发。

**未来测试类型**: 纵跳（Jump Test）只是第一个完成的测试类型，目的是 **建立一套完整的范式**（参数配置 → 数据采集 → 实时分析 → 报告生成），方便后续扩展到步态分析、短跑、跑步机测试等更多类型。修改或新增代码时，应确保设计不硬编码于纵跳场景，而是遵循 `TestConfig.test_type` 分发的通用模式。

**未来硬件**: 将支持多米段设备级联（多对条形装置串联，LED 数量从 96 扩展到 N×96）。因此，当前模块中涉及 LED 数量、空间坐标、聚类算法的部分，**必须确保可扩展性**——避免硬编码 96 或单段假设。修改 `hardware/`、`engine/` 层代码时尤其注意这一点。

## 参数配置系统

系统架构详见 **[docs/architecture.md](docs/architecture.md)**。

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

## Agent 模块设计

详见 **[docs/architecture.md §8](docs/architecture.md)**。

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
| Agent 集成到主 UI | ✅ 已完成 | `agent_config_panel.py` 集成进 `SetupView` |
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
