# Iron_Jump 参数配置系统开发计划

## 已完成的基础设施

| 阶段 | 内容 | 关键文件 |
|---|---|---|
| P1 | 配置数据模型 | `config/param_schema.py`, `config/test_config.py` |
| P2 | Agent 模块重构（输出 TestConfig） | `agent/models.py`, `rule_engine.py`, `llm_agent.py`, `gait_agent.py` |
| P3 | 算法引擎适配（接受 TestConfig + 自动停止） | `engine/gait_engine.py` |
| P4 | UI 参数配置面板 | `ui/param_panel.py` |

当前已建立完整的 Jump Test 范式：参数配置 → 数据采集 → 实时分析 → 报告生成。以下计划均基于此范式扩展。

---

## 已确认决策

| 决策项 | 结论 |
|---|---|
| 滤波逻辑位置 | 在 `GaitEngine._accumulate_hop_stats()` 中做事后过滤，不在 `SingleFootDetector.consume()` 内部 |
| `External impulse` stop_type | 硬件层未实现，UI 选项保留但功能不可用 |
| overload 参数 | 暂不添加能量/功率计算 |
| Agent 框架 | PydanticAI 单框架 + ClarifyGPT 设计思想，不引入新依赖 |

---

## ✅ LLM 追问能力（已解决）

> 通过 `Union[LLMTestConfig, ChatResponse]` 让 LLM 自主选择输出类型，
> 信息不足时自动退回 ChatResponse 追问，不再硬猜配置。
> 追问可靠性由 ClarifyGPT 多采样机制保障。

---

## ✅ Phase 4.5: LLMTestConfig 结构化输出层（已完成）

> LLMTestConfig(BaseModel) 已实现，含 Literal/Field(ge/le) 约束 + `@field_validator("test_length")` 格式归一化 + `to_test_config()` 转换。
> LLM 输出 JSON → Pydantic 校验 → LLMTestConfig → to_test_config() → TestConfig → ParamSchema.validate() 三层校验链完整。

### 设计原则

- **不改 `TestConfig`** — 它是整个系统的通用配置（engine / ui / controller 都依赖），改为 BaseModel 牵一发而动全身
- **加转换层** — `LLMTestConfig(BaseModel)` 只在 `agent/llm_agent.py` 内部使用，通过 `.to_test_config()` 转换为系统通用的 `TestConfig`
- **无损转换** — `LLMTestConfig` 的约束更严格，任何通过它校验的值一定是 `TestConfig` 的合法值

### 数据流

```
LLM 输出 JSON
  → Pydantic 校验 → LLMTestConfig (BaseModel, 严格约束)
  → .to_test_config() → TestConfig (dataclass, 系统通用)
  → ParamSchema.validate() → 业务逻辑二次校验
```

### 改动文件

| 文件 | 改动 |
|---|---|
| `agent/models.py` | 新增 `LLMTestConfig(BaseModel)`，~50 行 |
| `agent/llm_agent.py` | `result_type` 从 `TestConfig` 改为 `LLMTestConfig`，chat() 中加 `.to_test_config()` 转换 |

### 已知风险：LLM 边界行为

> [!WARNING]
> 以下场景 LLM 可能处理不当，需在测试中重点验证：

| 场景 | 预期行为 | 潜在风险 | 应对策略 |
|---|---|---|---|
| 用户说"做50个跳，跳到跳不动也行" | number_of_jumps=50, stop_type="Status change" | LLM 可能误解"跳不动"为 End of Time | 依赖 SYSTEM_PROMPT 语义引导；未来由 ClarifyGPT 多采样检测分歧 |
| 用户说"测2分钟" | test_length="02:00", stop_type="End of Time" | LLM 可能输出 "2m"、"120s" 等非 mm:ss 格式 | `LLMTestConfig` 中对 `test_length` 加 `@field_validator` 校验 mm:ss 格式 |
| 用户说"最大腾空设2000" | max_flight_time=2000 | 在约束范围内 (0~5000)，正确 | — |
| 用户说"最大腾空设10000" | 无法生成 | 超出 le=5000，pydantic-ai 触发重试(retries=2)，LLM 可能坚持原值导致最终失败 | `chat()` 的 except 分支应返回有意义的错误提示而非裸异常信息 |

---

## Phase 4.8: 用户识别与参数复用

> 根据数据库中的历史受试者信息，自动识别回访用户并加载上次的测试参数，减少重复配置。
> 核心价值是**参数复用**，不是身份识别本身——不要过度设计识别环节。

### 设计决策

| 决策项 | 结论 | 理由 |
|---|---|---|
| 匹配方式 | 数据库直查，不用 LLM | 姓名匹配是字符串检索问题，不需要语义理解。LLM 延迟高、成本高、且结果不确定 |
| LLM 的角色 | 仅负责从自然语言中提取姓名（NER） | "我是李明，帮我配上次的参数" → 提取 "李明" → 交给数据库匹配 |
| 语音输入同音字 | 拼音中间层匹配（`pypinyin`） | 数据库规模小（几十~几百人）、有 UI 辅助确认，不需要工业级 ASR 纠错 |

### 数据流

```
用户输入（文字/语音 ASR 结果）
  → [LLM: 意图识别 + 姓名提取]
  → 姓名字符串
  → [三层匹配]:
      层级 1: 精确汉字匹配 → 唯一命中 → 加载历史参数
      层级 2: 拼音匹配 (pypinyin) → 唯一命中 → 加载历史参数（需用户确认汉字）
      层级 3: 多候选 → UI 弹出列表让操作员选择
      无命中 → 当作新用户，走正常配置流程
```

### 分阶段实施

| 子阶段 | 内容 | 工作量 |
|---|---|---|
| **4.8a (MVP)** | 打字输入姓名 → 精确匹配 → 命中则加载参数；未命中则走新用户流程 | 半天 |
| **4.8b** | 引入 `pypinyin`，构建拼音索引，精确匹配失败后降级拼音匹配，多候选弹确认列表 | 1 天 |
| **4.8c (按需)** | 语音输入优化：ASR 热词增强、N-best 候选匹配 | 2-3 天 |

> [!IMPORTANT]
> **先做 4.8a 验证"参数复用"本身是否被认可，再迭代后续子阶段。**

### 改动文件

| 文件 | 改动 |
|---|---|
| `agent/models.py` | 可能新增 `UserProfile` 数据模型 |
| `agent/llm_agent.py` 或 `agent/gait_agent.py` | 新增用户识别 → 参数加载的前置逻辑 |
| 新增 `data/user_db.py` 或类似模块 | 受试者信息存储与查询（精确匹配 + 拼音索引） |
| `requirements.txt` | 4.8b 阶段新增 `pypinyin` 依赖 |

---

## ✅ Phase 5: ClarifyGPT 模式集成（已完成）

> 借鉴 ClarifyGPT (ACM FSE 2024) 的 "Detect → Clarify → Refine" 思想，已实现。

### 核心原则

> **"代码做裁判，模型做分析"**

| 角色 | 负责方 | 职责 |
|:---|:---|:---|
| **裁判** | Python 代码 | 客观判定"有没有分歧"（`_find_disagreements()`） |
| **分析师** | LLM | 主观分析"为什么有分歧"并生成追问（`_generate_clarification()`） |

### 已实现方案

ClarifyGPT 原论文的核心方法论是"采样 N 个代码方案 → 按测试输出聚类 → 各组随机选代表"。本项目适配如下：

| ClarifyGPT 论文 | 本项目实现 | 对应代码 |
|---|---|---|
| 采样 N 个独立代码方案 | `asyncio.gather(N × agent.run())`，同快照、同事件循环 | `_verify_config` |
| 按测试输出聚类 | `_cluster_configs()`：按 `(stop_type, jumps, test_length)` 组合值分组 | `_cluster_configs()` |
| 每组随机选代表 → 问题生成 | 单组 → `random.choice()`；多组 → `_generate_clarification()` | `_verify_config`, `_generate_clarification()` |

具体优化项：
1. **异步并行采样**（P0）: `chat()` 内部用 `asyncio.run(_flow())` + `_verify_config()` 用 `asyncio.gather()` 同时发起 N-1 次 `agent.run()`。配置生成从 ~21s 降到 ~14s。所有 N 个样本地位平等
2. **聚类一致性检查**: `_cluster_configs()` 按 CRITICAL_FIELDS 分组，`_find_disagreements()` 做多值比较
3. **歧义追问**: `_generate_clarification()` 将分歧字段翻译为自然语言
4. **预热机制**（P1）: `switch_mode("online")` 时 `warmup()` 提前初始化 Agent，首次对话 ~20s→~5s
5. **SYSTEM_PROMPT 精简**（P2）: ~520 tokens→~257 tokens(-51%)
6. **规则引擎保守聚合**（P3）: `_apply_patient_rules()` 取最保守值，14 个单元测试覆盖

---

## Phase 6: 更多测试类型扩展

> 当前纵跳（Jump Test）是第一个范式，需扩展到其他测试类型。

### 目标测试类型

| 类型 | Iron_parameters.json 中的 key | 状态 |
|---|---|---|
| Jump Test | `Jump Test` | ✅ 已完成 |
| Sprint and Gait Test | `Sprint and Gait Test` | 📋 待开发 |
| Treadmill Running Test | `Treadmill Running Test` | 📋 待开发 |
| Treadmill Gait Test | `Treadmill Gait Test` | 📋 待开发 |
| Tapping Test | `Tapping Test` | 📋 待开发 |
| Reaction Times | `Reaction Times` | 📋 待开发 |
| Static Test (Sway) | `Static Test (Sway)` | 📋 待开发 |

### 扩展点

| 模块 | 需要做什么 |
|---|---|
| `config/test_config.py` | 为新测试类型添加特有字段（如步态的 stride_length_threshold 等） |
| `engine/gait_engine.py` | 步态模式的 `_process_gait()` 已存在骨架，需完善停止条件和滤波 |
| `agent/rule_engine.py` | `PATIENT_RULES` 添加非纵跳测试类型的规则 |
| `agent/llm_agent.py` | `SYSTEM_PROMPT` 扩展为覆盖多种测试类型的参数规则 |
| `ui/views/execution_view.py` | 不同测试类型的仪表盘布局和指标卡片 |
| `ui/views/report_view.py` | 不同测试类型的报告模板 |

---

## Phase 7: 硬件扩展

### 7a: External impulse 信号支持

当前 `UsbWorker._on_frame()` 只处理 `E_DATA_REPORT`，丢弃了 `E_STATUS_REPORT`。

| 改动文件 | 内容 |
|---|---|
| `hardware/usb_worker.py` | 新增 `status_signal`，转发 `E_STATUS_REPORT` 帧 |
| `engine/gait_engine.py` | 监听 status_signal，实现 `External impulse` 自动停止 |

### 7b: 多米段设备级联

当前所有模块假设单米段（96 LED）。级联后 LED 数量变为 N×96。

| 改动文件 | 关注点 |
|---|---|
| `hardware/usb_worker.py` | 数据拼接：多段设备的帧合并 |
| `engine/spatial_clusterer.py` | 聚类算法：坐标空间从 [0, 96) 扩展到 [0, N×96) |
| `engine/single_foot_tracker.py` | 触地比例计算：`bits[:96]` 等硬编码需参数化 |
| `engine/contact_tracker.py` | 步长/步速计算：物理距离映射需适配多段 |
| `config/test_config.py` | 可能新增设备拓扑配置（段数、排列方式） |

---

## Phase 8: 其他待定项

| 项目 | 说明 | 优先级 |
|---|---|---|
| overload 参数 / 能量功率计算 | 需要 `body_weight` 输入，公式待确认 | 低 |
| PDF 导出 | ReportView 增加 PDF 导出能力 | 低 |
| 受试者档案管理 | Dashboard 页管理受试者信息，关联历史测试（基础识别见 Phase 4.8） | 低 |
| Agent 集成到主 UI | 将 `agent_test_ui.py` 的功能嵌入 SetupView | 中 |
| Markdown 表格渲染 | ✅ 已解决：`QTextDocument.setDefaultStyleSheet()` 嵌入 table/td/th 边框 CSS + markdown-it-py.enable("table") | 中 |
| 底层参数沉默 | min_contact_time/min_flight_time/max_flight_time 已加 SYSTEM_PROMPT 沉默规则 + 移出 ClarifyGPT 分歧检查，LLM 偶有违反 | 低 |

---

## Phase 9: PyQt 架构分层改造计划

> 目标不是“大搬家”，而是在不破坏当前 Jump Test 工作流的前提下，逐步把 Qt、硬件、文件导出等外层细节从业务核心中剥离出来。

### 当前判断

| 模块 | 当前状态 | 主要问题 |
|---|---|---|
| `ui/session_controller.py` | 已承担 Qt 会话协调职责 | 可以继续作为 Presenter/Controller，但不应长期读取或修改 engine 私有字段 |
| `engine/gait_engine.py` | 算法 + Qt QObject/Signal/QTimer 混合 | 算法核心还不能完全脱离 Qt 单独测试 |
| `hardware/usb_worker.py` | USB 读取 + 帧解析 + Qt 信号 + UI 节流混合 | 硬件解析逻辑不够独立，后续多米段和状态帧扩展会变重 |
| `ui/views/report_view.py` | View 内直接生成 Excel | 文件导出属于基础设施能力，应从 View 中移出 |
| `engine/single_foot_tracker.py` / `engine/spatial_clusterer.py` | 有 `96`、`1.04cm` 等硬件假设 | 多米段设备级联时需要参数化 |

### 成功标准

1. 算法核心可以不启动 Qt 直接跑单元测试。
2. USB/相机/Excel 这类外部系统都在外层，业务代码不直接依赖。
3. 当前 Jump Test 的配置、采集、实时分析、报告工作流不退化。
4. 新测试类型、多米段设备、Agent 主 UI 集成都有明确扩展点。
5. 每个阶段都有测试或可运行检查，不靠手工观察判断“应该没问题”。

### 目标结构

```text
Iron_Jump/
├── ui/                         # Qt 界面、视图、Qt Controller、Qt Worker
│   ├── views/
│   ├── workers/
│   └── session_controller.py
├── application/                # 用例编排：开始测试、停止测试、生成报告
│   ├── session_service.py
│   └── report_service.py
├── engine/                     # 纯算法/领域逻辑
│   ├── gait_core.py
│   ├── single_foot_tracker.py
│   ├── contact_tracker.py
│   └── spatial_clusterer.py
├── hardware/                   # 纯硬件协议、DLL、USB 读取，不放 Qt
│   ├── protocol.py
│   ├── receive.py
│   └── frame_decoder.py
├── infrastructure/             # Excel、文件、相机 SDK、持久化
│   ├── excel_exporter.py
│   └── camera/
├── config/                     # 参数 schema / TestConfig
├── agent/                      # 规则引擎 + LLM 配置助手
└── tests/
```

### 分阶段执行

| 阶段 | 内容 | 验证 |
|---|---|---|
| 9.0 锁定现状 | 补齐测试依赖和测试入口；先让现有 `tests/` 可运行 | `python -m pytest -q tests` 通过 |
| 9.1 加保护测试 | 给 `single_foot_tracker`、`spatial_clusterer`、`contact_tracker`、`build_report` 加小样本测试 | 不接硬件也能验证算法输出 |
| 9.2 抽纯算法核心 | 新增 `engine/gait_core.py`，迁出 `GaitEngine` 中的状态机、统计、停止判断；现有 `GaitEngine(QObject)` 先保留为 Qt 适配壳 | `gait_core` 无 Qt import；原 UI 流程不变 |
| 9.3 拆 USB Worker | 把 bytes→bits、分包合并、contact_bits 转换抽到 `hardware/frame_decoder.py`；Qt 信号部分保留为薄 Worker | 帧解析可单测；Qt Worker 只负责生命周期和信号转发 |
| 9.4 改报告边界 | 让算法核心输出 `SessionSnapshot/TestResult`，`build_report()` 不再读取 engine 私有状态 | `SessionController` 不再直接改 `_paused/_finished` |
| 9.5 Excel 外移 | 把 `ReportView` 中的 Excel 生成移到 `infrastructure/excel_exporter.py` | Excel 导出逻辑可脱离 Qt 测试 |
| 9.6 参数化设备拓扑 | 新增 `DeviceTopology(segment_count, leds_per_segment=96, spacing_cm=1.04)`，逐步替换硬编码 | 单米段输出不变，多米段 fixture 可跑 |
| 9.7 Agent 集成主 UI | 不直接搬 `agent_test_ui.py`，在 `SetupView` 增加配置助手入口；LLM 调用继续用独立 Qt Worker | 主界面可生成并回填 `TestConfig` |
| 9.8 包入口清理 | 移除 `main_window.py` 中的 `sys.path` hack，改为稳定模块启动方式 | import 检查通过 |
| 9.9 文档收口 | 更新 README / 本计划，明确哪些层允许 Qt、哪些层禁止 Qt | 新增简单依赖检查脚本 |

### 优先级

先做 `9.0 → 9.1 → 9.2 → 9.3`。这四步收益最大，也最能降低后续扩展风险。不要先做大规模目录迁移，也不要先重写 UI；当前关键是把 `GaitEngine` 和 `UsbWorker` 变成薄适配壳，让算法和硬件解析被测试锁住。
