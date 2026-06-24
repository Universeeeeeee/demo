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

## 2026-06-23 状态校准与当前下一步

### 已落地但旧计划未同步

| 项目 | 当前代码事实 | 关键文件 |
|---|---|---|
| SubjectStore UI MVP | 已接入主 UI：受试者搜索/新建、加载上次参数、测试结束自动存档、历史记录回填配置 | `data/subject_store.py`, `ui/views/setup_view.py`, `ui/main_window.py`, `ui/views/history_view.py`, `tests/test_subject_store.py`, `tests/test_history_view.py` |
| Agent 集成主 UI | 已完成：`AgentConfigPanel` 嵌入 `SetupView`，支持智能/手动配置切换 | `ui/views/agent_config_panel.py`, `ui/views/setup_view.py`, `tests/test_agent_config_panel.py` |
| Phase 9.1 保护测试 | 已有小样本测试覆盖 single foot、spatial cluster、contact tracker、build_report | `tests/test_engine_protection.py`, `tests/test_jump_report.py` |

### 当前执行顺序

1. **论文 P0 主实验**：先设计步态参数准确性验证方案，确定参考标准、采集对照数据和评价指标。
2. **论文 P0 Agent 辅助实验**：编写 10~30 条典型指令，并实现 Agent 评估脚本。
3. **工程 Phase 9.2a → 9.2**：先升级纵跳离线诊断，验证“确认仍用高阈值、统计时间由关联原始轨迹回填”的方案；通过多 session 人工标注复验后，再小范围修改 `SingleFootDetector`。只有纵跳时间戳语义稳定后，才继续抽出 `engine/gait_core.py`，让 `GaitEngine(QObject)` 逐步变成 Qt 适配壳。

### 当前计算逻辑审计：边界记录 + 事件确认

| 模式 | 当前逻辑 | 判断 |
|---|---|---|
| 原始帧导出 | `GaitEngine.process_raw_frame()` 先把每帧 `contact_bits` 和相对时间写入 FIFO 导出缓存，再进入算法处理 | 记录的是全量帧，不是只记录边界 |
| 纵跳 Jump Test | `SingleFootDetector` 连续 `confirm_samples` 帧满足触地/离地条件后才发事件；事件时间使用**确认成功帧时间**。当前 `Jump Test` 配置为 `touch_ratio_threshold=0.12`、`lift_ratio_threshold=0.05`、`confirm_samples=2`，且 `_extract_primary_cluster()` 会过滤 `<10 LED` 的主簇。因此当前 lift 近似等价于“连续 2 帧没有长度 `>=10 LED` 的有效主簇”。`GaitEngine._accumulate_hop_stats()` 用确认后的 touch/lift 时间计算腾空、接触、周期。 | **只有事件确认，没有边界回填**。session5 离线诊断支持边界回填方向，但只是一组探索数据，不能直接作为生产改造证据 |
| 步态 Gait Test | `extract_clusters()` 每帧提取簇 `start/end/centroid`；`ClusterTracker` 维护 `appear_time/disappear_time`；`ContactBasedGaitTracker` 先 candidate，连续帧确认后 touch_time 回填 `first_seen_time`，丢失多帧确认后 lift_time 回填 `last_seen_time` | 是“边界记录 + 事件确认”：触地/离地都先记录边界，再等待确认 |

**2026-06-24 修订准则**：若旧文档仍写成“touch/lift 统一候选起点回填”或“纵跳已经确定改为简单边界记录 + 事件确认”，以以下结论为准：

1. 纵跳不拆成“小簇检测器”和“高阈值检测器”。每帧只做一次原始簇提取，得到 `raw_clusters`；`confirm_cluster` 是从同一份 `raw_clusters` 中按当前生产规则筛出的主簇。
2. `confirm_cluster` 仍是唯一事件确认依据；原始小簇不直接输出 touch/lift，只维护候选接触轨迹和边界时间。
3. touch 与 lift 不对称：touch 的统计边界是同一关联轨迹的 `first_seen_time`；lift 第一阶段只在**当前生产确认语义**成立时，回填确认前同一 active track 的 `last_seen_time`。
4. 第一阶段不升级 lift 确认规则。像 `12 LED -> 0 -> 5 LED -> 3 LED -> 0 -> 0` 这种序列，在当前生产语义下会在 `5 LED` 帧附近确认 lift，不能为了回填后续 `3 LED` 而暗中改变确认机制。
5. `FootEvent.time` 应表示统计用边界时间；`confirm_time` 表示确认成功帧时间；必要时再保留 `first_confirm_frame_time` 用于分析 `confirm_samples` 延迟。

**Phase 9.2a 离线验证范围**：

- 先扩展 `tools/jump_timing_diagnostics.py`，不要直接改 `GaitEngine`、UI、报告或生产纵跳链路。
- 对照至少拆成：A 当前确认成功帧；B 首个满足当前确认条件帧；C touch-only 关联 `first_seen`；D lift-only 在当前确认语义下关联 `last_seen`；E touch+lift 同时关联回填。
- `raw track` 匹配必须是一对一分配：一帧内一个 raw cluster 最多匹配一条 track，一条 active track 最多接收一个 raw cluster；可用稳定贪心评分，不需要先上 Hungarian。
- 早期小簇是否能接到确认簇，必须看时空连续性，而不是简单取窗口内最早非零帧。`1 LED` 簇不能只靠质心距离连接，至少要满足区间重叠、边缘接近，或连续相邻帧持续出现。
- `max_missing_frames`、`max_edge_gap_led`、`max_centroid_shift_led`、`max_touch_candidate_age_ms` 都是实验候选参数，不是生产常量。先输出 `candidate_to_confirm_ms` 分布，再决定是否硬过滤。
- 主指标是 `contact_time MAE`、`air_time MAE` 和事件匹配稳定性；`jump_height MAE` 只是由 `air_time` 推导出的报告层影响，除非有独立参考设备，否则不作为独立证据。
- 生产准入最低要求：至少 3 个独立采集 session、15~20 个已匹配完整跳跃；每个 session 单独算 MAE；多数 session 不劣于当前基线；不增加漏检、误检、配对失败；`fallback_rate` 必须为 0 或有可解释例外。

---

## 🔴 Phase 0: 论文创新点 — 面向步态分析系统的 Agent 参数配置与意图澄清模块（最高优先级）

> **论文主线**：步态分析系统设计与实现（数据采集 → 参数计算 → 结果可视化 → 报告生成）
>
> **Agent 定位**：系统交互层 / 智能配置模块，**不是独立研究课题**。用于降低系统使用门槛，让用户通过自然语言完成分析任务配置。
>
> **关键判断**：主实验验证**步态参数准确性**，Agent 只做**轻量级模块可用性验证**（10~30 条典型场景）。Agent 不需要大规模数据集，但必须有最小验证，不能只靠引用论文支撑。
>
> **讨论记录**：
> - `chatgpt.md` 全文 — 与 ChatGPT 的完整研究讨论（ClarifyGPT 综述 → 意图检测主流框架 → Pydantic AI + ClarifyGPT 组合评价 → 创新点建议 → 评价指标设计 → **论文主线纠偏：Agent 降权为创新点之一**）
> - 2026-05-15 与 Claude 对话 (Round 1) — 对照 chatgpt.md 建议逐项审计代码实现，识别差距
> - 2026-05-15 与 Claude 对话 (Round 2) — 根据 chatgpt.md 更新内容重写 Phase 0，论文主线从 Agent 拉回步态分析

### 论文三贡献（最终版）

```text
1. 设计并实现一个步态分析系统，支持步态数据输入、关键参数提取、
   结果展示与报告生成。

2. 提出一套步态参数计算与验证流程，对步频、步长、步速、步态周期
   等指标进行计算，并通过对比实验验证系统准确性。

3. 设计一个面向步态分析任务的 Agent 参数配置模块，借鉴 ClarifyGPT
   的多采样一致性检测思想，结合 Pydantic 结构化输出实现自然语言到
   分析配置的转换，并通过典型场景测试验证其可用性。
```

### Agent 的论文表述（降权版）

> 在系统交互层，本文借鉴 ClarifyGPT (ACM FSE 2024) 的多采样一致性检测与意图澄清思想，设计了面向步态分析参数配置的 Agent 模块。该模块通过 Pydantic 约束结构化 JSON 输出，并在多次采样配置不一致时触发澄清问题，以减少用户自然语言配置中的歧义。

**为什么表述要降权**：论文主线是步态分析，不能写成 "ClarifyGPT for Agent Configuration"。Agent 是锦上添花，不是主角。

### 理论依据（论文引用即可，不需要自建数据集验证）

| 依据 | 来源 | 引用目的 |
|---|---|---|
| ClarifyGPT 多采样一致性检测 + 澄清问题生成 | ACM FSE 2024 | 说明 Agent 歧义检测与追问机制有理论来源 |
| Pydantic AI 结构化输出（JSON Schema + 校验） | pydantic.dev docs | 说明工程选型的合理性 |
| 意图检测主流框架综述（Intent + Slot → DST → LLM 路由） | Rasa / arXiv 2101.08091 / OpenAI | 说明 Agent 设计参考了成熟的技术路线 |

### 实验设计（两层结构）

#### 主实验：步态参数准确性验证（论文重心）

```text
系统计算值 vs 人工标注 / 参考系统 / 标准数据

指标：MAE / RMSE / 相对误差 / 相关系数 / ICC / Bland-Altman
```

参考做法：步态分析系统验证文献通常和参考系统（GAITRite、Vicon、Qualisys 等）比较时空步态参数或运动学参数，报告准确性、有效性或一致性。

#### 辅助实验：Agent 配置模块可用性验证（控制篇幅）

**规模**：10~30 条典型用户指令（不叫"数据集"，叫"典型使用场景测试用例"）

| 类型 | 示例指令 | 验证点 |
|---|---|---|
| 明确指令 | "分析视频中的步频、步长和步速，输出图表" | 是否能直接生成合法配置 |
| 缺参数指令 | "帮我分析一下步态" | 是否能追问分析指标或输入来源 |
| 模糊指令 | "给我详细一点的结果" | 是否能追问详细程度、指标范围 |
| 冲突指令 | "快速分析，但要输出完整三维运动学参数" | 是否能识别配置冲突 |
| 格式指令 | "结果导出成 Excel" | 是否能正确配置输出格式 |

**Agent 评价指标（轻量级，3 项即可）**：

| 指标 | 作用 |
|---|---|
| 配置生成成功率 | 用户指令能否生成合法 JSON 配置 |
| 关键参数正确率 | 生成配置里的关键步态分析参数是否正确 |
| 澄清有效率 | 模糊指令下，系统是否能问到关键缺失参数 |

**对比 baseline（简化版）**：

| 方法 | 说明 |
|---|---|
| Single Agent 单次配置 | 无多采样、无澄清追问 |
| 本方法（Pydantic + 多采样一致性 + 澄清机制） | 当前实现 |

不需要做 5 组 baseline 的大规模对比。

### 当前实现 vs 论文要求 — 差距清单（重分级）

| 差距项 | 当前实现 | 论文需要 | 优先级 |
|---|---|---|---|
| Agent 典型场景测试用例 | 无 | 10~30 条指令 + 3 项指标评估 | **P0** |
| 步态参数准确性验证方案 | 无 | MAE / RMSE / ICC / Bland-Altman 对比实验 | **P0**（主实验） |
| 一致性度量 | 二分法（1组/多组） | 当前二分法对 Agent 辅助实验已够用，无需量化分数 | ~~P0~~ → **够用** |
| 追问生成 | 模板拼接 | 当前模板对步态参数场景已够用，无需歧义类型分类 | ~~P1~~ → **够用** |
| 语义等价比较 | `==` 字段级比较 | 步态参数字段均为枚举/整数，字段级比较已足够 | ~~P0~~ → **够用** |

### 论文版 TODO（重新分级）

- [ ] **P0（主实验）** 设计步态参数准确性验证方案：确定参考标准、采集对照数据、选定评价指标
- [ ] **P0（Agent）** 编写 10~30 条典型用户指令测试用例，覆盖明确/缺参数/模糊/冲突/格式 5 类场景
- [ ] **P0（Agent）** 实现 Agent 评估脚本：配置生成成功率 / 关键参数正确率 / 澄清有效率
- [x] **P1** Agent 集成到主 UI（SetupView 配置助手入口），不在独立 `agent_test_ui.py` 中验证
- [ ] **P2** `LLMTestConfig` 新增 `confidence` 字段（锦上添花，非必需）

### 对应代码位置

| 论文概念 | 代码位置 | 需改动 |
|---|---|---|
| 结构化输出 | `agent/models.py` — `LLMTestConfig` | 可选加 `confidence` |
| 多采样一致性检测 | `agent/llm_agent.py` — `_verify_config()`, `_cluster_configs()`, `_find_disagreements()` | 当前实现已够用 |
| 差异驱动追问 | `agent/llm_agent.py` — `_generate_clarification()` | 当前实现已够用 |
| Pydantic 校验链 | `agent/models.py` → `config/param_schema.py` | 无 |
| 典型场景测试 | 新文件 `tests/test_agent_scenarios.py` | 新建 |

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

### 当前状态（2026-06-23）

| 子阶段 | 状态 | 说明 |
|---|---|---|
| 4.8a MVP | ✅ 已完成 | 主 UI 支持打字搜索受试者、精确/LIKE 查询、创建受试者、加载上次参数、测试结束自动记录 session |
| 4.8b 拼音匹配 | 📋 待开发 | 暂未引入 `pypinyin`，不做同音字匹配 |
| 4.8c 语音输入优化 | 📋 按需 | 暂未做 ASR 热词或 N-best 候选匹配 |

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
6. **规则引擎保守聚合**（P3）: `_apply_rules()` 取最保守值，14 个单元测试覆盖

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
| `agent/rule_engine.py` | `PROFILE_RULES` 添加非纵跳测试类型的规则 |
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
| 受试者档案管理 | 基础受试者选择和历史记录已接入；Dashboard 页集中管理受试者信息仍可后续补 | 低 |
| Agent 集成到主 UI | ✅ 已完成：`AgentConfigPanel` 已嵌入 SetupView | 已完成 |
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
| ✅ 9.0 锁定现状 | 已补齐测试入口依赖并消除 pytest 收集警告；现有 `tests/` 可统一运行 | 2026-06-08: `python -m pytest -q tests` → 32 passed |
| ✅ 9.1 加保护测试 | 已给 `single_foot_tracker`、`spatial_clusterer`、`contact_tracker`、`build_report` 加小样本测试 | `tests/test_engine_protection.py`, `tests/test_jump_report.py` |
| 9.2a 纵跳时间戳离线验证 | session5 仅证明“事件确认时间”和“统计边界时间”值得拆开验证；下一步先更新离线诊断工具，比较 A 当前确认帧、B 首个确认条件帧、C touch-only 关联 `first_seen`、D lift-only 关联 `last_seen`、E touch+lift 关联回填。第一阶段 lift 只回填当前确认前的 `last_seen`，不升级确认语义 | 保护 Jump Test 指标不被边界偏移污染；至少 3 个独立 session / 15~20 个完整跳跃通过后，再给 `SingleFootDetector` 写失败测试并实现 `FootEvent.time`=边界时间、`confirm_time`=确认帧时间 |
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
