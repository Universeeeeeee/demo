# 面向运动测试的 Agent 编排式可信分析与报告系统

> 最终架构、角色边界与工程落地方案
>
> 历史方案稿：不再作为当前实现或论文材料来源。当前方案以 `ReportAgentArchitecture_0808.md` v2.0 为准。

本文以既有《AI 在运动测试系统报告生成与分析中的角色与边界》为可信治理底座，并吸收后续需求讨论形成可实施的系统方案。论文写作相关内容已迁移至项目根目录的 `素材.md`。

## 执行摘要

运动测试系统处理的是高频采集数据、严格定义的指标和可重复验证的比较结果。纵跳、跑步机步态和跑步分析中的接触时间、腾空时间、步频、步长、速度、变化率、分位数、不对称、重复性和数据充分性，应由确定性算法、统计方法或受控分析 Tool 计算。让通用大语言模型直接读取数据库并自行完成这些计算，会引入数值错误、基线混用、不可复现、隐私和审计风险。

AI 在结果阶段不只承担语言润色。分析 Agent 根据基础事实主动提出分析问题，从注册表中选择经过验证的 Skill，调用确定性 Tool 获取原报告未预先展示的派生结果，再结合结构化参考标准和文献资料，自主确定分析重点并组织智能分析报告。Agent 不拥有公式定义权和底层事实修改权，但拥有受限的分析调度权、证据综合权、发现排序权和报告组织权。

> 最终产品定位：面向运动测试的 Agent 编排式可信分析系统。系统通过确定性算法完成测量与统计计算；分析 Agent 根据基础事实提出分析问题，调用经过验证的领域 Tool 获取派生指标，结合结构化参考标准和文献知识生成可追溯的智能分析，并支持用户持续追问和重分析。

该方案保留基础报告的离线可用、确定性、可测试和可审计属性，同时使 AI 成为后续分析与报告组织的主体。程序和 Tool 负责生成可验证事实，Agent 决定何时深入分析并组织报告，规则与校验器限制数据范围、声明强度和禁止推断，知识系统提供可追溯的解释依据。联网状态下，通过校验的结果显示在报告的固定智能分析区域；离线状态下不显示该区域。

| 层级 | 主要职责 | 核心技术 | 报告呈现方式 |
| --- | --- | --- | --- |
| 测量证据层 | 采集、事件识别、基础指标、数据质量 | 确定性状态机、公式、统计 | 始终进入基础报告 |
| 分析能力层 | 历史与团队查询、派生指标、协议兼容判断 | 只读领域 Tool、Capability Registry | 作为智能分析的事实依据 |
| Agent 编排层 | 提出分析假设、选择 Skill、调用 Tool、综合证据、组织报告 | LLM Agent、Capability Registry | 联网且校验通过后进入固定智能分析区域 |
| 知识与校验层 | 常模匹配、声明边界、文献解释与引用校验 | 结构化标准库、RAG、Validator | 提供来源、限制并阻断不合格声明 |
| 交互呈现层 | 固定智能分析区域、图表、追问和重分析 | 分析会话、状态化 UI | 联网显示，离线隐藏 |

## 最终系统方案

### 1. 问题定义与设计目标

现有系统支持纵跳、跑步机步态和跑步分析，完成硬件数据采集、运动指标计算、报告生成以及运动员、团队和历史记录管理。AI 已用于测试前的自然语言参数配置：用户用自然语言描述测试需求，LLM 生成结构化配置，系统再执行确定性校验。该场景的合理性来自输入的开放性，而不是计算本身的不确定性。

结果阶段的核心矛盾是：横向比较、纵向趋势、变化率、百分位、不对称和数据充分性都可以由程序稳定实现；单纯让 LLM 润色规则结论属于装饰性 AI；让 LLM 自由分析数值又会降低准确性与可解释性。另一方面，如果 AI 只停留在测试前配置，产品又缺少贯穿测试流程的智能交互。

最终方案的目标不是让 LLM 替代统计分析，而是解决以下更适合 Agent 的开放决策问题：

- 在大量基础指标和候选发现中，本次测试最值得深入分析的问题是什么。

- 是否需要调用原始报告之外的确定性分析能力，例如阶段比较、滚动变异性、异常试次敏感性或变化点检测。

- 哪些深层结果相互支持，哪些结果只是噪声、协议差异或样本不足。

- 如何在不要求用户额外填写背景的前提下，组织本次重点发现与后续追问入口。

- 如何把数据依据、算法依据、规则依据和文献依据绑定到同一条可审计声明。

### 2. 最终设计原则

| 原则 | 具体要求 | 工程含义 |
| --- | --- | --- |
| 事实外置 | 所有数值和统计结果均由确定性代码产生 | LLM 输出不得出现 Fact/Tool 输出中不存在的数字 |
| 算法预注册 | Agent 只能选择已审核 Tool/Skill，不能临时编写公式 | 分析能力进入 Capability Registry 并版本化 |
| 声明受校验约束 | 阈值、样本门槛和禁止推断由规则与校验器定义 | Agent 不得把相关性升级为因果、诊断或处方 |
| 零额外输入 | 默认分析不要求用户再次描述测试背景 | 自动使用 test_type、协议、历史记录和已有配置意图 |
| 基础事实与智能分析分层 | 基础测试事实不可修改，Agent 负责智能分析区域 | 联网时校验后自动显示，离线时不显示 |
| 可重放 | 每次 Tool 调用、检索与声明均可复现 | 记录输入快照、版本、参数、来源和校验结果 |
| 渐进增强 | 无 LLM、无网络时基础报告仍完整可用 | AI 不成为基础事实交付链路的单点依赖 |
| 按 test_type 分发 | 能力、规则、协议和阈值不写死在 Jump Test | 支持纵跳、步态、跑步及后续测试类型扩展 |
| 硬件边界稳定 | 保持 1000 Hz，兼容未来 N×96 级联 | 不修改高频链路，不硬编码单段 96 LED |

> 边界总则：测量事实和数值运算由确定性算法或受控 Tool 完成；开放问题、分析路径选择、证据综合、知识解释和报告组织由 Agent 完成；规则与校验器负责限制权限和声明边界。

### 3. 角色与权限边界

| 能力 | 确定性系统 | 分析 Agent | 知识系统/用户 |
| --- | --- | --- | --- |
| 基础指标计算 | 定义并执行 | 不可修改，只能引用 | 无 |
| 历史与团队查询 | 按受限接口和权限执行 | 选择允许的查询 Tool | 用户可切换基线策略 |
| 深层派生计算 | Tool 执行固定算法 | 决定是否调用及调用顺序 | 专家审核 Tool 定义 |
| 异常或偏离分析 | Tool 计算偏离量并检查样本门槛 | 结合多项事实形成分析并排序 | 标准库提供适用范围 |
| 报告章节 | 提供不可修改的基础区域和固定智能分析位置 | 组织智能分析内容与优先级 | 用户可展开、追问或重新分析 |
| 文献解释 | 不负责自由生成 | 基于检索片段组织解释 | RAG 返回来源和适用条件 |
| 训练/损伤结论 | 默认禁止 | 默认禁止 | 需未来独立验证与专业审批 |
| 基础结果修改 | 基础测试事实保持不可修改 | 禁止 | 无 |

这里必须区分“Agent 计算”和“Agent 调用计算”。前者意味着模型自己进行算术、选择公式甚至临时编写代码，不可接受；后者意味着模型从受控能力目录中选择确定性函数，函数依据固定输入、固定版本和固定参数执行，并返回可验证结果，可以接受。

### 4. Tool、Skill 与 Agent 的职责划分

Tool 是最小可测试计算单元，Skill 是经审核的分析流程，Agent 是受约束的调度者。三者应形成稳定边界，而不能把所有逻辑塞入一个提示词。

| 组件 | 定义 | 典型示例 | 必须满足的约束 |
| --- | --- | --- | --- |
| Tool | 确定性、单一职责的计算或查询函数 | compare_early_late_phase、compute_rolling_variability、get_protocol_matched_history | 明确 schema、单位、样本门槛、版本、测试覆盖 |
| Skill | 由多个 Tool 组成的领域分析流程 | 纵跳试次稳定性、跑步机后段漂移、跑步节律一致性 | 声明适用 test_type、前置条件、停止条件和禁止推断 |
| Agent | 读取事实、提出假设、选择 Skill/Tool 并组织结果 | 发现平均值掩盖后半程波动并发起阶段分析 | 不可定义公式、不可绕过门槛、不可修改 Tool 返回值 |

建议第一版只允许 Agent 在一次分析中执行最多两步 Tool 调用，避免开放式递归规划。随着 Tool 覆盖率、错误处理和审计机制成熟，再逐步开放多步 Skill。

### 5. 深层派生分析的价值与边界

常规报告通常展示预先定义的平均值、极值和固定比较。如果基础指标表面正常，但时序内部存在阶段性漂移、试次间波动或极端试次影响，静态模板可能无法主动发现。Agent 的增量价值在于提出“是否还需要算一个此前未展示的派生指标”，而不是重新解释已有数字。

| 测试类型 | 基础迹象 | 可调用的深层 Tool/Skill | 允许形成的补充发现 |
| --- | --- | --- | --- |
| 纵跳 | 平均跳高下降或试次离散 | 试次稳定性、首末试次比较、异常试次敏感性 | 表现变化是否由单个试次主导；重复性是否下降 |
| 跑步机步态 | 平均触地时间正常但波动增加 | 前后阶段比较、滚动 CV、速度一致性控制 | 后段一致性下降；变化是否在恒定跑速下仍存在 |
| 跑步 | 整体步频正常但局部节律漂移 | 分段趋势、变化点检测、触地时间—速度关系 | 某阶段发生持续漂移；均值是否掩盖局部变化 |
| 通用质量 | 结果极端或相邻事件异常 | 排除试次重算、故障注入匹配、最近邻异常案例 | 结果是否对可疑试次敏感；建议复核而非直接删除 |

当前红外光电传感器能够支持时空事件、连续节律、位置与遮挡模式相关分析，但不能直接观察关节角度、地面反作用力、关节力矩、肌肉激活和真实质心轨迹。因此，任何 Tool/Skill 都必须在能力注册表中声明 observable_outputs 与 prohibited_inferences。

- 允许：触地/腾空时间、步频、步长或位置变化、连续稳定性、阶段漂移、双侧差异、同协议历史趋势。

- 禁止：由当前光电传感器数据直接推断膝髋踝角度、肌肉状态、具体疲劳机制、病理诊断或损伤概率。

- 谨慎：可描述“后段一致性下降”“偏离个人近期波动范围”，但不直接写成“疲劳导致”或“存在损伤隐患”。

### 6. Analysis Capability Registry

所有可被 Agent 调用的分析能力必须注册，而不是由提示词动态发明。注册表既是权限白名单，也是测试、版本和审计的入口。

```python
@dataclass(frozen=True)
class AnalysisCapability:
    capability_id: str
    version: str
    test_types: tuple[str, ...]
    required_inputs: tuple[str, ...]
    minimum_samples: int
    assumptions: tuple[str, ...]
    output_metrics: tuple[str, ...]
    observable_outputs: tuple[str, ...]
    prohibited_inferences: tuple[str, ...]
    max_runtime_ms: int
    validator_ids: tuple[str, ...]
```

注册表至少需要解决四类问题：能力是否适用于当前 test_type；数据和样本是否满足前置条件；输出能够支持什么强度的声明；失败时是否回退到已有正式报告。

### 7. 分析假设与派生事实模型

Agent 不应直接输出一段自由文本，而应先形成结构化分析假设。假设用于解释“为什么需要调用这个 Tool”，派生事实用于记录“Tool 实际算出了什么”，最终声明再绑定二者。

```python
class AnalysisHypothesis(BaseModel):
    hypothesis_id: str
    description: str
    trigger_fact_ids: list[str]
    selected_skill_id: str
    expected_outputs: list[str]
    priority: Literal["low", "medium", "high"]
class DerivedFact(BaseModel):
    fact_id: str
    metric_code: str
    value: float | str
    unit: str | None
    tool_run_id: str
    input_snapshot_id: str
    tool_version: str
    parameters: dict[str, object]
    limitations: list[str]
```

只有当 Tool 返回结果通过 schema、单位、范围、样本门槛和领域规则校验后，DerivedFact 才能进入智能分析。Agent 的原始推测本身不能进入报告。

### 8. 知识系统：结构化标准库、规则库与文献 RAG

对于“特别优异”“明显偏低”“值得关注”等判断，必须有适用的参考依据。将全部知识写入 Prompt 会浪费 Token、难以版本化，也无法严格匹配人群与协议。单一向量 RAG 同样不足，因为数值阈值、统计标准和文献解释具有不同的数据结构。最终方案采用三层混合知识系统。

| 知识层 | 主要内容 | 检索方式 | 在结论中的作用 |
| --- | --- | --- | --- |
| 结构化参考标准库 | 常模、分位数、参考范围、样本量、协议、人群 | 字段过滤 + 精确查询 | 判断是否偏离适用参考范围 |
| 规则知识库 | 样本门槛、测量误差、MDC/SWC、禁止推断、措辞强度 | 规则匹配 + 标签检索 | 限制结论强度与适用边界 |
| 文献 RAG | 指标含义、常见混淆因素、方法学依据、解释材料 | 关键词 + 向量 + 元数据过滤 + rerank | 解释“如何理解”，不负责重算或诊断 |

数值标准不能只依赖语义相似度。参考项必须至少匹配 test_type、protocol_version、metric_definition_version、设备配置、年龄/性别/项目/水平等可用人群字段，并显示样本量与适用限制。找不到严格匹配标准时，应退回个人基线、团队内部参考或“无适用外部常模”，而不是选择最相似的文献强行评价。

### 9. 证据绑定声明与角标引用

每条智能分析声明应同时绑定数据依据和知识依据。文献角标只能说明一般知识或参考标准来源，不能证明某个运动员出现该结果的具体原因。因此建议将声明分为 measurement、comparison、interpretation 和 hypothesis 四个层级。

```python
class EvidenceBoundClaim(BaseModel):
    claim_id: str
    text: str
    claim_level: Literal[
        "measurement", "comparison", "interpretation", "hypothesis"
    ]
    base_fact_ids: list[str]
    derived_fact_ids: list[str]
    tool_run_ids: list[str]
    reference_ids: list[str]
    applicability_note: str | None
    limitations: list[str]
    confidence: Literal["low", "medium", "high"]
```

| 声明类型 | 示例 | 必须绑定的依据 | 是否允许进入智能分析区域 |
| --- | --- | --- | --- |
| Measurement | 后 30% 阶段步间 CV 为 8.1% | DerivedFact、Tool Run、输入快照 | 是 |
| Comparison | 较前 30% 阶段增加 32% | 两个事实、比较算法版本 | 是 |
| Interpretation | 提示本次后段动作一致性下降 | 事实 + 规则/文献 + 限制 | 是 |
| Hypothesis | 可能与疲劳或策略调整有关 | 文献可支持可能性，但缺少个体因果证据 | 默认仅在会话中，明确标为待验证 |

渲染器负责把 reference_id 转换为角标，并在“依据”面板中显示文献标题、作者、年份、具体页码/表格/章节、适用人群和支持范围。模型不得自行编造编号、作者、DOI 或页码。

### 10. 正式报告与动态重点模块

“AI 动态决定报告结构”需要收紧为“固定信息架构，动态内容优先级”。整份报告不能由模型任意创建章节，否则不同报告难以比较、快照测试和审计。正式报告应保留固定骨架，Agent 只能从审核过的 Section Registry 中选择动态模块并调整展示顺序。

| 固定骨架 | 动态可选模块 | Agent 权限 |
| --- | --- | --- |
| 测试与协议信息 | 无 | 不可省略或修改 |
| 数据质量与有效性 | 可疑试次敏感性 | 可以增加复核模块 |
| 核心指标表 | 本次重点发现卡片 | 只能排序，不能修改数值 |
| 标准纵向/横向比较 | 阶段漂移、滚动稳定性、变化点 | 满足前置条件时调用并加入 |
| 基础结果与确定性图表 | 智能分析内容 | 联网且校验通过后显示在固定区域 |
| 方法、限制与来源 | 知识解释与角标详情 | 可扩展但不可删除限制 |

“特别优异/特别差”不应由 Agent 自由感觉判断。规则层应输出更中性的等级，例如：信息、值得关注、建议复测、数据不足、测试无效；Agent 再根据严重度、用户可操作性和本次发现间的一致性决定是否在顶部突出显示。

### 11. 分析会话：从问答助手到状态化分析工作台

分析会话是本方案最重要的产品形态。它不是在报告旁边增加一个普通聊天框，而是让用户通过自然语言发起新的受控分析。每次回答都应经历“理解问题—生成分析计划—调用 Tool—更新事实和图表—验证声明—返回可追溯答案”的流程。

| 用户问题 | Agent 动作 | 确定性执行 | 输出 |
| --- | --- | --- | --- |
| 去掉第一次试跳后结论是否变化？ | 选择试次敏感性 Skill | 排除指定试次重算均值/CV | 新旧结果、结论是否稳健、限制 |
| 前半程和后半程差异在哪里？ | 选择阶段比较 Skill | 固定分段并计算阶段指标 | 差异指标、趋势图、数据依据 |
| 为什么平均值正常仍提示稳定性下降？ | 检索相关 Fact 和规则 | 不新增计算或按需调用滚动变异性 | 均值与波动指标的区别及来源 |
| 只比较最近一个月会怎样？ | 选择受限历史查询 Tool | 按同协议、日期和版本生成新快照 | 新比较结果和快照 ID |
| 与团队同位置运动员比较 | 检查字段与样本门槛 | 生成匹配 cohort 快照 | 样本量、分位数、适用限制 |

会话中的重新分析结果仍需绑定 claim_id、fact_ids、tool_run_ids、reference_ids、数据快照和报告模板版本。通过校验后，最新结果更新固定智能分析区域，但不得修改基础测试事实。

### 12. 零额外输入与上下文获取

系统使用 AI 的目标是降低操作成本，不应要求用户为了让 Agent 发挥作用而再次输入“近期训练负荷较大、关注疲劳”等背景。默认分析必须在零额外输入下工作。可用上下文按优先级如下：

1. 本次 TestReport：test_type、协议、指标、试次和数据质量。

2. 同运动员、同协议、兼容指标版本的历史记录。

3. 团队或分层参考快照及样本量。

4. 测试前自然语言配置中已经出现的意图，但单独保存为 AnalysisContext，不污染 TestConfig。

5. 已有操作员备注和标签，且仅在权限与隐私允许时使用。

```python
class AnalysisContext(BaseModel):
    intent_tags: list[str] = []
    target_capabilities: list[str] = []
    comparison_preference: str | None = None
    source: Literal["config_agent", "system_default", "user_session"]
    user_constraints: list[str] = []
```

若完全没有意图信息，系统按 test_type 执行默认低成本 Skill。只有当某个分析结论确实依赖无法推断的条件时，才在会话中提出非阻塞式问题；用户不回答也不影响正式报告。

### 13. 推荐系统架构

```text
hardware/
    USB 通信、1000 Hz 原始数据获取、N×96 级联元数据
engine/
    事件识别、基础运动指标、TestReport（frozen dataclass）
analysis/
    protocols/          # jump / treadmill_gait / running / future test_type
    comparison/         # 纵向、cohort、可靠性与参考快照
    tools/              # 确定性深层计算原子
    skills/             # 经审核的分析流程
    capabilities/       # 白名单、版本、前置条件与禁止推断
    rules/              # Finding 与结论强度
    quality/            # 硬质量门与后续异常模型
    schemas/            # Fact、DerivedFact、Claim、ToolRun
knowledge/
    references/         # 结构化常模和参考标准
    rules/              # 方法学边界和专家知识条目
    literature/         # 文献 RAG 索引
ai/
    config_agent/       # LLMTestConfig -> TestConfig
    analysis_agent/     # 假设、Skill 选择和 Tool 调度
    validators/         # 数字、单位、声明、引用与禁用推断校验
report/
    assembler/          # 固定骨架 + Section Registry
    templates/
    renderer/
conversation/
    session_state/
    analysis_actions/
```

该结构不要求修改 hardware/ 和 engine/ 的核心职责。高频 UsbWorker 到 GaitEngine 链路继续保持现有设计；分析 Agent 位于测试完成后的低频链路，不接触实时 1000 Hz UI 更新，也不使 GaitEngine 依赖 QtWidgets。

### 14. 核心数据对象

```python
@dataclass(frozen=True)
class ToolRunRecord:
    tool_run_id: str
    capability_id: str
    capability_version: str
    input_snapshot_id: str
    parameters: Mapping[str, object]
    output_fact_ids: tuple[str, ...]
    started_at: datetime
    duration_ms: int
    status: Literal["success", "rejected", "failed"]
    validator_result: str
@dataclass(frozen=True)
class AnalysisPackage:
    report_id: str
    base_fact_bundle_id: str
    hypotheses: tuple[AnalysisHypothesis, ...]
    derived_facts: tuple[DerivedFact, ...]
    claims: tuple[EvidenceBoundClaim, ...]
    tool_runs: tuple[ToolRunRecord, ...]
    reference_snapshot_ids: tuple[str, ...]
    knowledge_version: str
    agent_trace_id: str
```

TestReport 保持不可变。Agent 产生的 AnalysisPackage 是附加对象，不覆盖原始事实。这样可以独立删除或重新生成 AI 分析，同时保持原报告和历史比较的一致性。

### 15. 端到端执行流程

1. 测试结束，engine 生成不可变 TestReport。

2. 确定性分析层生成基础 FactBundle、标准比较、数据质量与规则 Finding。

3. 正式报告立即按固定模板生成，不等待 LLM。

4. 分析 Agent 读取去标识化且权限受限的事实与 Capability Registry。

5. Agent 提出候选 AnalysisHypothesis，并由策略层检查是否值得调用 Tool。

6. 应用层执行确定性 Tool/Skill，生成 ToolRunRecord 与 DerivedFact。

7. 规则层根据样本门槛、测量误差和禁止推断生成 Exploratory Finding。

8. 知识系统检索适用标准和文献片段，生成 source_id 与 applicability_note。

9. Claim Validator 检查数字、单位、方向、结论强度、来源与隐私。

10. 分析工作台展示重点发现、图表、依据和限制；用户可继续追问。

11. 通过校验的 Claim 写入报告的固定智能分析区域，并记录完整审计信息。

### 16. 数据访问与隐私边界

不向模型暴露通用只读 SQL。只读权限只能防止写入，不能防止跨运动员查询、过量数据返回、错误基线、协议混用或不可重放路径。所有数据访问均通过领域 Tool，由应用层执行权限、范围和协议校验。

| 数据 | 本地确定性分析 | 外部/云端 LLM |
| --- | --- | --- |
| 运动员姓名与联系方式 | 按权限展示 | 不发送 |
| 团队名称 | 可展示 | 匿名化或不发送 |
| 原始 1000 Hz 时序 | 本地保存与 Tool 处理 | 默认不发送 |
| 历史完整记录 | 本地受限查询 | 不发送 |
| 聚合 Fact/DerivedFact | 完整保存 | 按需发送最小去标识子集 |
| 视频与伤病备注 | 未来独立限权处理 | 默认禁止发送 |
| 检索来源与规则版本 | 本地记录 | 可发送无个人信息的 ID/片段 |

### 17. 校验、失败安全与审计

Agent 不是可靠性的来源，校验器和回退机制才是。任何 AI 输出失败都必须回退到确定性正式报告，不能阻塞报告交付。

| 校验器 | 检查内容 | 失败处理 |
| --- | --- | --- |
| Tool Input Validator | test_type、协议、样本数、单位、权限 | 拒绝调用并返回原因 |
| Fact Validator | 输出类型、范围、NaN、单位和算法不变量 | 丢弃 DerivedFact |
| Claim Validator | 未知数字、方向颠倒、强度升级、禁止推断 | 阻断声明或使用规则模板 |
| Citation Validator | source_id 存在、支持范围、适用人群、定位信息 | 移除引用或降级为无外部标准 |
| Privacy Validator | 姓名、团队、病史和过量上下文 | 脱敏或禁止发送 |
| Budget/Loop Guard | 调用次数、Token、延迟和递归深度 | 停止深入分析，保留已有结果 |

审计日志至少记录 report_id、raw_data_hash、test_type、protocol_version、metric_engine_version、ruleset_version、Tool/Skill 版本、输入快照、模型与 Prompt 版本、检索文档版本、Validator 结果、blocked_claims、延迟和成本。

### 18. 测试策略

分析层应被视为高可信数据处理模块，而不是普通文本功能。测试体系分为确定性引擎测试、Agent 决策测试和端到端事实挑战测试。

| 测试类别 | 主要方法 | 关键成功标准 |
| --- | --- | --- |
| Tool 单元测试 | 黄金数据、边界值、统计包交叉验证 | 固定输入输出完全一致 |
| 变形测试 | 试次顺序打乱、左右互换、N×96 平移、无关 test_type 插入 | 应保持的不变量成立 |
| Capability 测试 | 缺输入、样本不足、协议不兼容、权限不足 | Agent 无法绕过注册约束 |
| Agent 规划测试 | 给定 FactBundle 检查 Tool 选择与停止条件 | 不调用无关/高风险 Tool |
| 事实挑战集 | 零分母、单位混合、方向冲突、MDC/SWC 冲突 | 无未知数字和错误强度 |
| 引用测试 | 不匹配人群、过期条目、无定位信息 | 引用被拒绝或明确降级 |
| 报告快照 | 固定 AnalysisPackage 生成 JSON/HTML/PDF | 事实、规则 ID 和角标稳定 |
| 用户任务测试 | 教练/运动员查看依据、追问、重算和切换基线 | 操作成本和理解效果待测量 |

### 19. MVP 范围与实施路线

第一版不应同时覆盖所有 test_type、全量论文 RAG 和自由多轮 Agent。推荐以 Jump Test 为最小闭环，证明“Agent 调用确定性 Tool”相对静态报告有真实增量。

| 阶段 | 实现内容 | 交付物 | 成功标准 |
| --- | --- | --- | --- |
| 阶段 0：可信底座 | 指标版本、协议、FactBundle、Finding、审计链 | 确定性正式报告 | 零 LLM 完整运行，可重放 |
| 阶段 1：Jump Tool | 稳定性、首末试次、异常试次敏感性 | 3 个 Tool + 单测 | 黄金数据与边界测试通过 |
| 阶段 2：受限 Agent | 最多两步 Tool 调用、结构化 Hypothesis | Agent 原型与 Capability Registry | 不出现越权调用和未知数字 |
| 阶段 3：知识解释 | 20—50 条审核知识条目、结构化引用 | 混合知识检索与角标 | 引用适用性人工准确率达标 |
| 阶段 4：分析会话 | 追问、重算、动态图表、更新智能分析区域 | 状态化工作台 | 典型任务可完成且全程可追溯 |
| 阶段 5：扩展测试类型 | 跑步机步态、跑步 Skill | 按 test_type 注册能力 | 无 Jump Test 硬编码 |
| 后续：学习型异常 | 规则质量门 + 简单无监督基线 | 异常复核模块 | 发现经专家确认的新质量问题 |

### 20. 第一版推荐 Tool/Skill

| 测试类型 | Tool/Skill | 输入 | 输出 |
| --- | --- | --- | --- |
| Jump | within_session_variability | 多次有效试跳指标 | CV、极差、稳健离散度、规则状态 |
| Jump | trial_sensitivity | 试次列表、排除策略 | 排除前后均值/CV及结论稳定性 |
| Jump | early_late_trial_comparison | 按顺序的试次指标 | 前后段差异与方向 |
| Treadmill gait | phase_drift_analysis | 连续步与跑带条件 | 前后阶段变化、滚动趋势 |
| Treadmill gait | bilateral_persistence | 左右侧连续指标 | 差异幅度、方向和持续性 |
| Running | rhythm_consistency | 步频、触地时间、速度序列 | 局部漂移与稳定性 |
| 通用 | protocol_matched_history | 运动员、协议、版本和时间窗 | 可审计历史快照 |
| 通用 | cohort_reference | 团队与分层条件 | 样本量、中位数、分位数和限制 |

### 21. 最终需求基线

| 编号 | 需求 |
| --- | --- |
| R1 | 正式报告在零 LLM、无网络条件下完整运行。 |
| R2 | Agent 不直接计算，不生成临时公式或执行自由代码。 |
| R3 | Agent 只能调用注册、版本化并通过测试的领域 Tool/Skill。 |
| R4 | 不向 Agent 提供通用 SQL 或任意数据库浏览权限。 |
| R5 | 每个 Tool 输出记录输入快照、参数、版本、限制和校验结果。 |
| R6 | 基础 Finding、DerivedFact 与 Agent Claim 分层存储。 |
| R7 | AI 声明必须绑定 Fact、Tool Run、规则和知识来源。 |
| R8 | RAG 采用结构化标准库、规则库和文献库的混合架构。 |
| R9 | 默认分析不要求用户额外输入测试背景。 |
| R10 | 基础报告采用固定结构，并为智能分析保留固定区域。 |
| R11 | 联网时通过校验的 Agent 输出自动进入固定智能分析区域；离线时不显示该区域。 |
| R12 | Agent 输出不得修改基础测试事实，并保存完整审计记录。 |
| R13 | 当前禁止医疗诊断、损伤概率和自动训练处方。 |
| R14 | 所有能力按 test_type、协议和指标版本分发。 |
| R15 | 采样率固定 1000 Hz，所有空间处理兼容 N×96 级联。 |
| R16 | TestReport 保持 frozen dataclass，AI 结果存入独立 AnalysisPackage。 |
| R17 | LLM 输出校验失败时不显示该次智能分析，基础报告保持可用。 |
| R18 | 每段 AI 输出可查看“为什么”、数据依据、来源和限制。 |
| R19 | 分析会话支持重算、切换受限基线、更新图表和刷新智能分析内容。 |
| R20 | Agent 调用深度、延迟、Token 和成本均有上限。 |

### 22. 成功标准与暂不实施项

| 维度 | 建议成功标准 |
| --- | --- |
| 事实正确性 | 数字、单位、方向和样本量完全来自 Fact/Tool 输出；未知数字率为 0。 |
| 权限安全 | Agent 无法调用不适用 test_type、样本不足或协议不兼容的能力。 |
| 可复现性 | 给定相同数据快照、Tool 版本和参数，DerivedFact 完全一致。 |
| 引用质量 | 每个角标可定位到真实条目并显示适用范围；不存在模型生成的虚假来源。 |
| 产品价值 | 用户能够通过会话完成静态报告无法直接完成的重分析任务。 |
| 失败安全 | 模型、检索或网络失败不影响正式报告，所有失败均可解释。 |
| 可维护性 | 新增 test_type 或 Tool 不要求修改通用 Agent 核心流程。 |

当前暂不实施：损伤风险预测、病理诊断、康复处方、自动训练处方、自由 SQL、Agent 自由编写代码、仅凭光电传感器数据推断关节动力学，以及将无监督异常分数直接写成运动学异常。

### 23. 最终结论

附件中的可信边界与最终方案并不冲突。客观事实由算法或受控 Tool 计算，分析 Agent 主动发现值得深入的问题、组织数据与知识证据并生成智能分析内容，规则与校验器负责限制权限、声明强度和禁止推断。

> 最终协作边界：开放输入由模型理解，客观事实由算法计算，派生指标由受控 Tool 生成，知识背景由检索系统提供，分析流程和报告内容由 Agent 组织，规则与校验器负责约束数据范围和声明边界。

这种架构既不为了展示 AI 而牺牲可信度，也不把 AI 限制为语言润色。静态报告无法提前穷举所有分析路径，Agent 可以根据本次事实按需调用已验证能力并组织报告；Agent 不能自创算法、修改基础事实或绕过校验边界。


## 结语

本方案的目标不是让大模型替代运动科学、统计方法或确定性软件，而是在明确事实计算、只读 Tool、声明校验和证据追溯边界后，使 Agent 成为运动测试分析与智能报告组织的主体。联网状态下，通过校验的分析结果显示在报告的固定智能分析区域，并支持后续追问和可验证重算；离线状态下不显示该区域，基础报告仍保持确定性、稳定性和可审计性。
