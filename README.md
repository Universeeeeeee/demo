# Iron_Jump — Agent Onboarding Guide

> **读者**: AI coding agent。本文档旨在让你在最短时间内理解项目的架构、约束和当前状态，避免犯已经讨论过的错误。
>
> **当前计划**: 具体进度、验证状态和后续任务以 [plan.md](plan.md) 为准；本文只保留稳定的项目入口和开发约束。

## 项目本质

这是一个 **OptoJump 兼容的纵跳、跑步机步态与跑步分析系统**。硬件是两根分别放置在两侧的条形装置，每根包含 96 个红外 LED，通过 USB 连接 PC，以 1000Hz 采样率实时上报每个 LED 的遮挡状态。软件侧负责：接收原始数据 → 按测试模式检测触地/离地与步态周期 → UI 实时展示 → 生成测试报告 → 保存历史记录。

### ⚠️ 当前范围与扩展性规划

**当前硬件**: 仅一对一米段条形装置（每根 96 个红外 LED）。多米段级联尚未实现，因此涉及 LED 数量、空间坐标、聚类和距离映射的代码仍需避免继续扩大单段假设。

**当前测试类型**:

- `Jump Test`：纵跳触地/腾空分析。
- `Treadmill Gait Test`：跑步机步态、双支撑和步态周期分析。
- `Treadmill Running Test`：跑步机跑步、接触/腾空和步态周期分析。

`Sprint and Gait`、`Tapping`、`Reaction Times`、`Static Test (Sway)` 等模式尚未实现。新增模式应遵循 `TestConfig.test_type → mode processor → report` 的分发方式，不能把新逻辑塞回 Jump 分支。

## 核心数据流

```text
USB 光栅（1000Hz）
  → UsbWorker
  → GaitEngine
  → JumpProcessor / TreadmillProcessor
  → 实时事件、步态周期和 FootprintVisualFrame
  → SessionController
  → ExecutionView / TestReport / SubjectStore

Tiny SE 相机
  → 嵌入式 16:9 预览与异步录像保存
  → 未镜像分析帧 + DirectShow 时间元数据
  → Vision Session 录制 / 人工标注 / 离线 Replay
  → 独立 vision 验证模块（尚未写回主流程）

不可变 TestReport
  → ReportDataPackage / AgentObservation
  → Report Agent 单步序贯分析决策
  → Action Validator + 确定性 Analysis Kernel
  → Evidence 状态归约 + Claim Validator
  → 报告页智能分析结果
```

关键边界：

- 光栅负责精确触地/离地时间；视觉只提供可拒识的 `Left / Right / Unknown` 参考标签，不承担双脚落地识别。
- `GaitEngine` 通过模式 processor 分发，不直接包含各模式的完整业务实现。
- `ReportView` 消费不可变报告快照，不应读取运行中的 engine 状态。
- 足迹由 engine 生成固定 cadence 的 canonical timeline，实时页和报告复用同一数据源。

## 参数配置系统

系统架构详见 **[docs/architecture.md](docs/architecture.md)**。

### 术语对照

项目中涉及"参数"一词时有四种不同含义，代码和文档中不应混用：

| 中文术语 | 代码类型 | 含义 |
|:---|:---|:---|
| 配置参数 | `TestConfig` (dataclass) | 测试开始前由用户或系统设定，参与采集、停止、过滤、计算 |
| 会话元数据 | `SessionMetadata` | 测试开始时冻结的受试者或环境信息，不一定是算法阈值 |
| 结果参数 | `ResultMetric` | 测试后从光栅事件和配置计算出的逐步或逐周期结果 |
| 汇总统计 | `MetricSummary` (dataclass) | 对结果参数做 min/max/mean/std/CV、左右脚、不对称性统计 |

数据库保存的配置快照称为"配置快照"，报告快照称为"报告快照"。

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

当前 Agent 已分为两个业务域：

- `agent/config/`：测试前自然语言配置，保留 Fast Gate、并行多采样和业务校验。
- `agent/report/`：测试后智能分析。Agent 只能从三个受控分析 Tool 中选择已启用能力及其确定性分析方法，并综合已绑定证据；正式数值由 Analysis Kernel 计算，Claim 必须通过 Evidence、Numeric Binding、权限及禁用语义校验。

两类 Agent 共用 `agent/common/` 的模型提供器，并由单一 Worker 按路由隔离状态。Report Agent 的生产默认配置为 AnalysisSketch + Compact Series，Screening Cues 与 Replan 默认关闭。

### 其他关键实现细节

- **RuleEngine**: `PROFILE_RULES` 是 `list[tuple[Callable, dict]]`，数据驱动。多规则命中同一字段时取最保守值（`min_contact→MAX`, `number_of_jumps→MIN`, `max_flight→MIN(非零)`），与规则添加顺序无关。14 个单元测试覆盖
- **LLMConfigAgent**: 延迟初始化 (`_ensure_agent()`) + 预热 (`warmup()`)，避免导入崩溃，首次对话不卡。chat() 同步接口，内部 `asyncio.run()` 统一事件循环以支持并行验证
- **三层校验**: ① Pydantic BaseModel 校验结构+范围+枚举 → ② `.to_test_config()` 转换 → ③ ParamSchema 校验跨字段联动

### ClarifyGPT 模式 (已实现)

借鉴 ClarifyGPT (ACM FSE 2024) 的 "Detect → Clarify → Refine" 思想:
1. **多次采样**: LLM 独立生成 N 份配置 (`N_SAMPLES=3`)；`_verify_config()` 用 `asyncio.gather()` 并行生成 peer 样本
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

# 运行全量自动化测试
python -m pytest -q

# 查看独立视觉诊断/真实光栅验证器参数
python tools/vision_diagnostic.py --help
python tools/vision_event_validator.py --help

# 启动左右脚视觉数据统一桌面工具
python vision_app.py

# 验证 import 链
python -c "from agent import GaitAgent, AthleteProfile; print('OK')"
python -c "from ui.main_window import MainWindow; print('OK')"
```

### Windows 视觉数据工具打包

根目录的 `build_vision_app.bat` 使用 PyInstaller `onedir` 构建统一启动器：

```text
dist/IronJumpVisionTools/IronJumpVisionTools.exe
```

构建脚本会检查运行依赖、按需安装 PyInstaller，并只清理本应用对应的
`build/dist` 目录。如果构建时存在
`models/pose_landmarker_full.task`，模型会一并复制；否则 App 首次录制时会
要求用户选择模型文件。正式数据和日志默认保存到：

```text
%USERPROFILE%\Documents\IronJump\vision_sessions
%USERPROFILE%\Documents\IronJump\app_logs
```

双击 EXE 后可选择“录制新 Session”“标注已有 Session”或“Replay 已有
Session”。子工具由同一个 EXE 以独立进程运行，不会创建嵌套 Qt 事件循环。

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

2026-08-12 全量回归基线（`QT_QPA_PLATFORM=offscreen`）：`659 passed`、`12 subtests passed`。

| 模块 | 状态 | 说明 |
|:---|:---|:---|
| hardware/ (L1) | ✅ 已实现 | 单对 96 LED 光栅采集；Jack 口 / External impulse 与多米段级联未实现 |
| engine/ (L2) | ✅ 已实现 | Jump、Treadmill Gait、Treadmill Running 三种 processor；跑步机真实准确性仍待验证 |
| config/ | ✅ 已实现 | 三种测试的配置、ParamSchema、报告模型和序列化入口 |
| ui/ 多视图 | ✅ 已接入 | Setup → Execution → Report，包含历史记录、相机、足迹和步态周期显示 |
| ui/data_show.py | 🔒 保留 | 旧版回退方案 |
| data/ 用户与团队 | ✅ 已接入 | 多团队成员关系、测试身份快照、主档案/会话快照分离及个人/团队历史查询 |
| 跑步机步态周期 | 🧪 自动化已验证 | 同侧周期、边界片段、阶段指标和不对称统计已接入；缺真实帧真值对照 |
| 足迹可视化 | ✅ 已接入 | 双 96 LED 实时通道及报告 `visual_timeline` 回放 |
| Tiny SE 相机 | 🔬 真机验证中 | 嵌入式预览、参数控制和异步录像保存已实现；1080p@100fps 待 Windows 确认 |
| vision/ 左右脚参考 | 🔬 独立验证中 | MediaPipe + TinySE 时间同步已实现；当前不写回 engine、报告或主 UI |
| agent/ 规则引擎 | ✅ 已实现 | 3 条规则，保守聚合 + 顺序无关，14 个单元测试 |
| agent/ LLM 配置 | ✅ 已接入 | 三种测试独立 prompt，Pydantic 结构化转换和 ClarifyGPT 多采样 |
| agent/ Report Agent | 🧪 合成数据已验证 | B 观察配置与单步序贯循环为生产默认；序贯 Benchmark Recall 0.9259，尚未完成真实运动员数据验证 |
| Vision 数据工具 | 🧪 源码已完成 | 录制、标注、Replay、QtPy 启动器和 PyInstaller onedir；Windows EXE 与硬件实机待验收 |

## 当前限制

- 跑步机步态周期已完成合成事件验证，但尚缺步态/跑步原始帧与 OptoJump 或人工真值对照。
- 跑步机步长结合跑带位移与相邻落点位置修正；步幅使用同侧完整周期计算。缺少可靠空间参考时不生成伪步幅，但真实设备准确性仍待对照实验。
- 视觉模块当前仅用于独立验证。受控左脚与右脚各 10 次基础检查通过，但随机顺序、连续同脚、交叉腿、踉跄、遮挡和跨受试者准确率仍待验证。
- Report Agent 当前结论来自固定合成模式，只能证明工程可行性，不能外推为真实训练或医学有效性。
- 2026-08-12 已完成此前跨功能工作区的拆分提交和敏感文件审计，全量自动化测试无失败。
- 纵跳关联轨迹算法目前是离线候选，尚未修改生产 `SingleFootDetector`。
- Tiny SE 的 UVC 模式、实际 1080p@100fps 和长时间 Windows 稳定性仍需真机确认。
- `External impulse`、多米段级联和其他 OptoJump 测试类型尚未实现。

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
11. **不要把缺失步态阶段写成 0** — 缺少必要的同侧/跨侧事件时使用 `N/A`，真实无重叠才是双支撑 0
12. **不要让视觉结果覆盖光栅事件时间** — 视觉尚未正式融合，并且只能作为可拒识的脚别参考
13. **不要用 `step_length × 2` 作为最终步幅结论** — 步幅必须来自同侧完整周期；缺少可靠参考时返回缺失而不是伪造数值
14. **不要把合成 Benchmark 当作真实准确率** — Report Agent 的当前结果只验证已知人工模式
15. **不要让 Report Agent 自由计算正式数值** — 只接受 Kernel 产生并通过 Numeric Binding 的 Fact

## 编码规范

参见 [AGENTS.md](AGENTS.md)。核心原则:
- **先想后写** — 不确定就问
- **最小改动** — 不 "改进" 无关代码
- **简洁优先** — 200 行能用 50 行就用 50 行
- **可验证** — 每步都有明确的成功标准
