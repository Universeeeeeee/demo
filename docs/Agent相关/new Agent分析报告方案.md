# 面向运动测试的 Agent 编排式可信分析与报告系统
## —— Analysis Planner + Deterministic Analysis Kernel 方案

> 历史方案稿：不再作为当前实现或论文材料来源。当前方案以 `ReportAgentArchitecture_0808.md` v2.0 为准。

## 1. 问题重新定义

此前为了降低 Token 和延迟，曾考虑采用如下方案：

```text
ReportDataPackage
    ↓
Deterministic Analysis Suite
    ↓
Insight Compiler
    ↓
NarrativePlan
    ↓
LLM 写作
```

该方案虽然高效，但存在一个根本问题：

> 它把“发现什么值得分析”“选择哪些分析路径”“如何组合多个分析维度”也交给了规则系统。

最终流程实际上退化为：

```text
规则计算候选模式
→ 规则筛选重点
→ 规则决定报告结构
→ LLM 负责表达
```

这与系统原本定义的 Agent 边界冲突。

本项目真正需要保留的是：

- Agent 提出分析问题；
- Agent 判断哪些现象值得进一步验证；
- Agent 选择横向、纵向、时序、左右侧等分析路径；
- Agent 组合多个分析维度；
- Agent 综合多个确定性分析结果。

而确定性系统负责：

- 数值读取；
- 数据过滤；
- 聚合；
- 比较；
- 趋势计算；
- 时序分析；
- 协议兼容性；
- 数据质量判断；
- 证据生成；
- 数值绑定与校验。

因此，优化的对象不应该是 **Agent 的分析能力**，而应该是：

> **多轮、低效率、重复上下文的 Tool Calling。**

---

# 2. 核心设计原则

最终推荐的职责边界可以概括为一句话：

> **Agent 决定“分析什么、为什么分析、如何组合”；确定性系统决定“怎么算”。**

换言之：

```text
预设分析能力
≠
预设所有分析结论
```

系统不再尝试用规则枚举：

```text
后半程触地时间增加
左侧变化更明显
步长同时下降
历史测试未出现
团队位置同时下降
```

这类复杂组合。

而是只提供一组稳定、受控、可组合的分析算子，让 Agent 根据当前报告内容自行构造分析路径。

---

# 3. 推荐总体架构

```text
┌──────────────────────────────┐
│      Immutable TestReport    │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│      ReportDataPackage       │
│   完整、可恢复、可追溯事实层 │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│        ProfileSketch         │
│  紧凑、中性、低 Token 概览  │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│     Agent Analysis Planner   │
│ 提出问题 / 选路径 / 组合维度 │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│       AnalysisPlan DAG       │
│      结构化分析执行计划      │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│         PlanValidator        │
│  权限 / 协议 / 成本 / 合法性 │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│ Deterministic Analysis Kernel│
│         批量并行执行         │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│        EvidenceBundle        │
│   Fact / Comparison / Quality│
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│       Agent Synthesis        │
│   跨维度综合 + 报告组织      │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│ Fact Binding + ClaimValidator│
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│       AnalysisPackage        │
└──────────────┬───────────────┘
               ↓
           报告 UI
```

对用户而言仍然只有一个操作：

```text
点击「智能分析」
        ↓
得到智能分析结果
```

内部不区分多种分析模式。

---

# 4. ReportDataPackage：完整证据层

`ReportDataPackage` 继续作为整个系统的权威语义数据层。

它负责保存：

- `ReportMetadata`
- `MetricCatalog`
- `BaseFacts`
- `RecordSet`
- `SeriesIndex`
- `QualityInformation`
- `ProvenanceInformation`
- 测试配置快照
- 协议版本
- 指标定义版本
- 原始帧和足迹引用
- 历史测试引用
- 团队快照引用

它的目标不是节约 Token，而是保证：

- 数据无损或近似无损；
- 顺序可恢复；
- 左右侧可恢复；
- 纳入 / 排除状态可恢复；
- 数值和单位可恢复；
- 数据质量可恢复；
- 每条最终声明能够追溯到具体事实。

Agent 默认不会直接读取完整 `ReportDataPackage`。

---

# 5. ProfileSketch：给 Agent 的低 Token 数据地图

## 5.1 ProfileSketch 的职责

`ProfileSketch` 只负责压缩数据表示，不负责判断“什么重要”。

它应该告诉 Agent：

- 当前是什么测试；
- 有哪些指标；
- 每个指标的基本统计情况；
- 是否存在左右侧；
- 是否存在时间序列；
- 是否存在历史数据；
- 是否存在团队数据；
- 数据质量如何；
- 哪些更细粒度数据可以继续分析。

它不能输出：

```text
“值得重点关注”
“存在明显退化”
“该指标优先级很高”
```

这些属于 Agent 的分析判断。

---

## 5.2 ProfileSketch 示例

```json
{
  "test_type": "treadmill_gait",
  "quality_status": "usable_with_limits",

  "metrics": [
    {
      "metric_code": "contact_time",
      "unit": "ms",
      "n": 41,

      "overall": {
        "mean": 241,
        "sd": 14
      },

      "side_summary": {
        "left_mean": 248,
        "right_mean": 235
      },

      "segment_summary": {
        "early_mean": 236,
        "middle_mean": 240,
        "late_mean": 249
      },

      "capabilities": {
        "sequence": true,
        "side": true,
        "temporal": true,
        "longitudinal": true,
        "cohort": true
      },

      "series_ref": "ser_contact_time"
    }
  ],

  "longitudinal": {
    "available": true,
    "compatible_report_count": 3
  },

  "cohort": {
    "available": true,
    "sample_count": 18
  }
}
```

ProfileSketch 是：

> **数据目录 + 低成本统计草图**

而不是：

> **规则生成的洞察列表**

---

# 6. Agent Analysis Planner

这是整个新方案的核心。

Agent 第一次获得真正的分析自主权。

它读取：

```text
ReportMetadata
MetricCatalog 精简版
ProfileSketch
QualitySummary
历史 / 团队数据可用性
AnalysisOperatorCatalog
```

然后自主完成：

1. 提出值得回答的问题；
2. 选择需要验证的现象；
3. 决定使用哪些分析维度；
4. 组合多个分析算子；
5. 输出结构化 `AnalysisPlan`。

---

## 6.1 示例：Agent 自主提出问题

如果 ProfileSketch 显示：

```text
触地时间：
- 左 > 右
- 后程 > 前程

步长：
- 后程 < 前程

历史数据：
- 可用
```

Agent 可以提出：

> 后半程触地时间增加是否主要集中于左侧？这种变化是否同时伴随步长下降？该模式是否是本次测试中新出现的？

这个分析问题不需要开发者提前写规则。

---

# 7. AnalysisPlan DAG

Agent 不直接调用大量 Tool，而是一次性生成一个结构化分析计划。

示例：

```json
{
  "plan_id": "plan_001",

  "questions": [
    {
      "question_id": "q1",
      "question": "后程变化是否集中在左侧，并伴随步长下降？"
    }
  ],

  "nodes": [
    {
      "node_id": "n1",
      "op": "segment_compare",
      "metric": "contact_time",
      "group_by": "side",
      "segments": ["early", "late"]
    },

    {
      "node_id": "n2",
      "op": "segment_compare",
      "metric": "step_length",
      "group_by": "side",
      "segments": ["early", "late"]
    },

    {
      "node_id": "n3",
      "op": "cross_metric_relation",
      "metrics": [
        "contact_time",
        "step_length"
      ],
      "scope": {
        "side": "left",
        "segment": "late"
      }
    },

    {
      "node_id": "n4",
      "op": "longitudinal_compare",
      "metrics": [
        "contact_time",
        "step_length"
      ]
    }
  ]
}
```

---

# 8. 为什么采用 DAG / Batch Execution

传统 ReAct 流程：

```text
LLM
→ Tool 1
→ LLM
→ Tool 2
→ LLM
→ Tool 3
→ LLM
→ 最终报告
```

存在：

- 多次网络往返；
- 每轮重复上下文；
- Tool 结果不断进入 Prompt；
- Token 随调用次数增长；
- 延迟近似线性累积。

推荐：

```text
LLM
→ 一次生成完整 AnalysisPlan
→ 后端批量 / 并行执行
→ 一次返回 EvidenceBundle
→ LLM 综合
```

也就是：

> **Plan once → Execute batch → Synthesize once**

因此，仍然保留 Agent 分析能力，同时避免低效的多轮 Tool Loop。

---

# 9. Analysis Kernel：预设的是算子，不是模式

旧方案的问题是试图定义：

```text
EarlyLateAnalyzer
SidePersistenceAnalyzer
FatigueAnalyzer
LongitudinalAnalyzer
...
```

然后依赖大量模式规则。

新方案应该进一步抽象成稳定的 **Analysis Operator Algebra**。

例如：

## 9.1 数据选择算子

```text
select_metric
select_side
select_record_type
select_time_range
select_inclusion_status
```

## 9.2 分组算子

```text
group_by_side
group_by_segment
group_by_test_session
group_by_subject
```

## 9.3 聚合算子

```text
mean
std
cv
median
count
percentile
```

## 9.4 比较算子

```text
group_compare
segment_compare
current_vs_baseline
current_vs_cohort
```

## 9.5 时序算子

```text
window_statistics
trend
change_point
stage_compare
```

## 9.6 异常与敏感性

```text
outlier_influence
exclusion_sensitivity
missingness_analysis
```

## 9.7 跨指标关系

```text
cross_metric_relation
co_change
```

## 9.8 质量与协议

```text
protocol_compatibility
sample_size_check
quality_scope_check
```

---

# 10. 最重要的架构区别

## 旧方案

```text
开发者预设：
“什么模式值得关注”
```

例如：

```text
if late_contact_time > early_contact_time:
    ...
```

继续增加：

```text
if left_late_contact_time > right_late_contact_time:
    ...
```

再继续增加：

```text
if left_late_contact_time ↑
and left_step_length ↓
and history normal:
    ...
```

规则会组合爆炸。

---

## 新方案

开发者只提供：

```text
segment
side
compare
history
metric_relation
```

Agent 自己组合成：

```text
late
× left
× contact_time
× step_length
× longitudinal
```

因此：

> **开发者枚举分析能力，Agent 组合分析路径。**

这是避免规则爆炸的核心。

---

# 11. PlanValidator：约束 Agent，而不是替 Agent 分析

Agent 生成的 AnalysisPlan 不能直接执行。

`PlanValidator` 检查：

- `metric_code` 是否存在；
- 指标是否支持当前测试；
- 左右侧是否适用；
- sequence 是否存在；
- 历史数据是否存在；
- cohort 是否存在；
- 协议是否兼容；
- 样本量是否足够；
- operator 是否在白名单；
- 是否请求自由公式；
- 是否请求自由代码；
- 是否超出执行成本预算；
- DAG 是否存在循环；
- node dependency 是否有效。

关键原则：

> PlanValidator 只负责判断“能不能这样分析”，不负责判断“值不值得这样分析”。

后者仍然属于 Agent。

---

# 12. EvidenceBundle

Analysis Kernel 批量执行完成后，不返回大型原始数组，而返回结构化确定性结果。

```python
class EvidenceItem(BaseModel):
    evidence_id: str
    operator: str

    metric_codes: tuple[str, ...]
    scope: dict

    fact_ids: tuple[str, ...]
    comparison_ids: tuple[str, ...]

    finding_code: str | None

    quality_flag_ids: tuple[str, ...]
    provenance_id: str


class EvidenceBundle(BaseModel):
    plan_id: str
    question_ids: tuple[str, ...]

    evidence_items: tuple[EvidenceItem, ...]

    limitations: tuple[str, ...]
```

EvidenceBundle 要做到：

- 结果精确；
- 数值已计算；
- 可追溯；
- 不包含无关数据；
- Token 规模可控。

---

# 13. Agent Synthesis

第二次 LLM 阶段读取：

```text
原始分析问题
+
EvidenceBundle
+
关键 Fact
+
质量限制
```

然后完成：

- 判断哪些分析问题得到支持；
- 识别多个分析结果之间的关系；
- 综合横向、纵向、时序和左右差异；
- 决定报告最终重点；
- 组织语言；
- 控制声明强度。

此时 Agent 仍然是真正的分析者，而不仅仅是文本润色器。

---

# 14. 数值仍然必须由 Fact Binding 控制

Agent 不允许自由生成关键数字。

建议：

```text
“后半程左侧触地时间由 {early_left_ct}
变化至 {late_left_ct}，
同时步长由 {early_left_sl}
变化至 {late_left_sl}。”
```

然后本地：

```text
early_left_ct → Fact ID
late_left_ct  → Fact ID
early_left_sl → Fact ID
late_left_sl  → Fact ID
```

最终由 `FactRenderer` 注入精确数值和单位。

这样保留：

- Agent 的分析表达能力；
- 数值的确定性；
- 单位的一致性；
- 证据链。

---

# 15. ClaimValidator

最终声明还要经过确定性检查。

至少验证：

- 所有数字是否来自 Fact；
- Fact 是否属于当前 Report Snapshot；
- Evidence 是否真实存在；
- Tool / Operator 结果是否属于当前 AnalysisPlan；
- 单位是否匹配；
- 样本量是否允许该声明；
- 协议是否允许横向 / 纵向比较；
- QualityFlag 是否限制声明强度；
- 是否存在因果越界；
- 是否出现医学诊断；
- 是否出现无来源数字。

只有通过后才显示在 UI。

---

# 16. Token 和延迟控制

本方案不是靠删除 Agent 来节省 Token，而是通过三个机制优化。

## 16.1 ProfileSketch 替代完整 JSON

第一次模型输入只包含：

```text
Metadata
+
Compact Metric Profiles
+
Quality Summary
+
Data Availability
+
Operator Catalog
```

而不是：

```text
所有逐跳数组
所有逐步数组
所有步态周期
所有历史报告
所有团队成员数据
```

---

## 16.2 一次规划替代多轮 Tool Calling

从：

```text
LLM → Tool → LLM → Tool → LLM → Tool
```

变为：

```text
LLM → AnalysisPlan
          ↓
       Batch Execute
          ↓
      EvidenceBundle
          ↓
         LLM
```

模型调用通常只有：

```text
1. Planner
2. Synthesis
```

---

## 16.3 EvidenceBundle 只返回相关结果

AnalysisPlan 只执行 Agent 真正选中的路径。

后端无需把完整原始数组再次发送给模型。

---

# 17. 如何处理“隐藏趋势”

不能声称系统能够发现任意未知模式。

只要存在：

- 有限上下文；
- 禁止自由代码；
- 有限 Operator；

就一定存在能力边界。

真正合理的目标是：

> **不枚举所有 Pattern，而是让有限 Operator 可以组合出大量新的 Pattern。**

例如系统不提前定义：

```text
“后半程左侧触地时间增加且步长下降”
```

但 Agent 可以利用：

```text
segment_compare
+
side
+
contact_time
+
step_length
+
cross_metric_relation
```

动态构造该分析。

因此系统的分析能力边界取决于：

> **Analysis Operator Algebra 的表达能力。**

后续扩展系统时，应优先扩展：

```text
Operator
```

而不是不断增加：

```text
Pattern Rule
```

---

# 18. 单一 Skill 设计

系统仍然只需要一个用户可感知的智能分析流程。

可以定义一个总 Skill：

```text
analyze_test_report
```

内部流程：

```text
Phase 1
读取 ProfileSketch

Phase 2
提出 1～3 个高价值分析问题

Phase 3
生成 AnalysisPlan DAG

Phase 4
调用 execute_analysis_plan

Phase 5
读取 EvidenceBundle

Phase 6
跨维度综合

Phase 7
生成结构化 AnalysisPackage

Phase 8
本地 Fact Binding + Validation
```

Agent 不直接递归调用多个 Skill。

---

# 19. Tool 设计

Agent 面向的 Tool 数量应该尽可能少。

推荐核心只暴露一个：

```python
execute_analysis_plan(
    report_id: str,
    plan: AnalysisPlan,
) -> EvidenceBundle
```

Agent 不需要看到十几个底层 Tool。

底层 Operator 由 `Analysis Kernel` 内部管理。

优点：

- Prompt 中 Tool Schema 更小；
- Agent 更容易理解接口；
- 不需要多轮 Function Calling；
- 权限边界集中；
- 更容易记录一次完整执行；
- 更方便测试和重放。

---

# 20. MVP 推荐范围

## 第一阶段：保留完整证据层

实现：

```text
ReportDataPackage
MetricCatalog
Fact
RecordSet
SeriesIndex
QualityFlag
Provenance
```

---

## 第二阶段：ProfileSketch

实现：

```text
MetricProfileBuilder
QualitySummaryBuilder
DataAvailabilityBuilder
```

只做中性描述，不生成优先级判断。

---

## 第三阶段：Analysis Kernel

第一版 Operator 控制在约 8～12 个：

```text
aggregate
group_compare
segment_compare
window_statistics
trend
outlier_influence
exclusion_sensitivity
longitudinal_compare
cohort_compare
cross_metric_relation
protocol_compatibility
quality_check
```

---

## 第四阶段：AnalysisPlan

Pydantic 定义：

```text
AnalysisQuestion
AnalysisNode
AnalysisPlan
```

并实现：

```text
PlanValidator
DAG Executor
```

---

## 第五阶段：Agent Planner + Synthesis

沿用现有：

```text
DeepSeek Flash
非思考模式
```

Planner 一次调用：

```text
ProfileSketch
→ AnalysisPlan
```

Synthesis 一次调用：

```text
EvidenceBundle
→ AnalysisPackage
```

---

## 第六阶段：可信输出

实现：

```text
FactRenderer
ClaimValidator
AnalysisPackage
```

---

# 21. 验证指标

## 21.1 Agent 分析能力

构造包含以下组合的测试样本：

- 单一时序变化；
- 左右差异；
- 左右差异只在后半程出现；
- 一个指标变化、另一个指标稳定；
- 两个指标同步变化；
- 本次异常但历史正常；
- 本次正常但团队位置异常；
- 排除项导致结论反转；
- 协议不兼容。

验证：

```text
Analysis Question Recall
Relevant Plan Rate
Cross-dimension Discovery Rate
Unsupported Path Rate
```

---

## 21.2 数值可信性

目标：

```text
Numeric Accuracy = 100%
Evidence Resolution Rate = 100%
Unsupported Claim Rate = 0%
Protocol Misuse Rate = 0%
```

---

## 21.3 性能

记录：

```text
Planner Input Tokens
Planner Output Tokens
Synthesis Input Tokens
Synthesis Output Tokens
Total Token
LLM Call Count
Kernel Execution Time
TTFT
Total Latency
```

推荐目标：

```text
LLM Call Count = 2
```

不允许随着分析节点数量线性增加模型调用次数。

---

# 22. 新旧方案最终对比

| 维度 | 旧 Insight Compiler 方案 | 新 Analysis Planner 方案 |
|---|---|---|
| 谁提出分析问题 | 规则 | Agent |
| 谁选择分析路径 | 规则 | Agent |
| 谁组合多维指标 | 规则预设 | Agent |
| 谁执行计算 | 确定性程序 | 确定性 Kernel |
| 是否需要枚举 Pattern | 是 | 否 |
| 是否允许自由公式 | 否 | 否 |
| 是否允许自由代码 | 否 | 否 |
| LLM Tool 调用方式 | 无 / 或规则触发 | 一次 Plan 批量执行 |
| Token | 低 | 较低且可控 |
| 灵活性 | 低 | 高 |
| 可信性 | 高 | 高 |
| Agent 价值 | 很低 | 明确保留 |

---

# 23. 最终结论

本项目不应该走向两个极端。

## 极端一：规则主导

```text
规则发现问题
→ 规则选重点
→ LLM 写作
```

缺点：

- Agent 被架空；
- 规则不断膨胀；
- 很难覆盖复杂跨维度组合。

## 极端二：LLM 自由分析原始数据

```text
完整数据
→ Agent 自由计算 / 自由 Tool Loop
```

缺点：

- Token 高；
- 延迟高；
- 算术可靠性差；
- 难以审计；
- 难以重放。

## 推荐中间路线

```text
ProfileSketch
        ↓
Agent 自主提出问题
        ↓
AnalysisPlan DAG
        ↓
确定性 Analysis Kernel 批量执行
        ↓
EvidenceBundle
        ↓
Agent 基于证据综合
        ↓
Fact Binding + Validator
```

一句话总结：

> **预设分析能力，而不是预设所有分析结论。**

更完整地说：

> **让 Agent 在受治理的运动测试语义层上自主生成可执行分析计划，由确定性分析内核批量执行，再由 Agent 基于可追溯证据完成跨维度综合。**

这同时满足：

- 保留 Agent 编排价值；
- 避免规则穷举；
- 支持未预设跨维度组合；
- 限制 Agent 自由计算；
- 降低多轮 Tool Calling Token；
- 降低网络往返延迟；
- 保持数值确定性；
- 保持证据可追溯；
- 保持分析过程可验证和可重放。

---

# 参考资料

## 1. Aryn：LLM + Semantic Plan + Data Processing Engine

用于理解“LLM 生成语义计划、确定性系统执行”的架构思路。

- https://arxiv.org/abs/2409.00847

## 2. AgenticData：Semantic Operators + Semantic Plan

用于参考自然语言分析问题如何转换成可执行的语义分析计划。

- https://arxiv.org/abs/2508.05002

## 3. BatchDAG：批量 DAG 执行替代顺序 Agent 调用

用于参考“一次规划 → 批量并行执行 → 一次综合”的性能优化思想。

- https://arxiv.org/abs/2607.18241

> 注：该工作属于较新的预印本，更适合作为架构思想参考，而非成熟行业标准。

## 4. PlanningArena：复杂 Tool Planning 的可靠性评估

说明即使较强模型在复杂工具规划任务中仍存在明显错误，因此 AnalysisPlan 必须经过确定性 Validator。

- https://aclanthology.org/2025.acl-long.1499/

## 5. Cube Semantic Layer for AI Agents

用于参考 Agent 面向受治理的 metrics、dimensions、filters 进行分析，而不是直接访问底层数据的思路。

- https://cube.dev/articles/semantic-layer-for-ai-agents-2026

## 6. DeepSeek Tool Calls

当前 DeepSeek Flash 非思考模式可以继续作为 Planner 和 Synthesis 模型。

- https://api-docs.deepseek.com/guides/tool_calls

## 7. Operation-guided Neural Networks for High Fidelity Data-To-Text Generation

支持“计算由确定性系统完成，模型使用计算结果生成语言”的基本思想。

- https://aclanthology.org/D18-1422/

## 8. Data Views for Controllable Data-to-Text Generation

支持向 LLM 提供紧凑、有结构的数据视图，而不是完整底层数据。

- https://aclanthology.org/2023.inlg-main.16/
