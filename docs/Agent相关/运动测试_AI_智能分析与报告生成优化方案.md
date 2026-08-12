# 面向运动测试的低延迟可信 AI 智能分析与报告生成方案

> 历史方案稿：不再作为当前实现或论文材料来源。当前方案以 `ReportAgentArchitecture_0808.md` v2.0 为准。

## 1. 目标与设计结论

本系统只保留一个用户入口：**“智能分析”**。

用户点击后，系统内部统一执行一条固定流水线，不区分“标准报告”“增强报告”或“自由探索”等模式。

推荐架构：

```text
Immutable TestReport
        ↓
ReportDataPackage
        ↓
Deterministic Analysis Suite
        ↓
Insight Compiler
        ↓
InsightSnapshot
        ↓
NarrativePlan
        ↓
DeepSeek Flash（非思考模式，单次生成）
        ↓
Fact Renderer + Validator
        ↓
AnalysisPackage
        ↓
报告固定智能分析区域
```

核心思想不是让 LLM 自己阅读整份报告、搜索数据并逐步决定调用什么工具，而是：

1. **确定性程序负责计算和筛查；**
2. **Insight Compiler 负责从大量确定性结果中选择真正值得写入报告的内容；**
3. **LLM 只负责跨维度综合、解释与自然语言组织；**
4. **所有数字、证据和质量限制由本地程序绑定和校验。**

这是一种面向运动测试场景的 **Data-to-Text Compiler**，比“完整 JSON + Agent 多轮 Tool Calling”更适合作为默认报告生成架构。

---

## 2. 为什么需要从多轮 Agent 改为单流水线

原方案：

```text
ReportManifest
    ↓
Agent 选择分析方向
    ↓
Tool 1
    ↓
Agent 再判断
    ↓
Tool 2
    ↓
Agent 再判断
    ↓
...
    ↓
最终综合
```

它的优点是灵活，但对于运动测试报告存在明显问题：

- 每轮 Tool 调用都会重新产生模型输入和输出；
- Agent 需要反复读取中间结果；
- 网络往返增加延迟；
- Tool 数量增加后，Prompt 和 Tool Schema 本身也会占用 Token；
- 大部分常规运动测试分析实际上是可预定义的；
- 同一份报告重复分析时，Agent 可能选择不同路径；
- 复杂编排增加错误面和测试成本。

运动测试和开放式科研问答不同。系统已经拥有确定性的步态、纵跳和跑步指标，真正需要 AI 完成的是：

> **从已经计算并筛选过的可靠事实中，选择合适的表达方式并形成有逻辑的综合结论。**

因此，常规分析不需要让 LLM 在数据空间中“探索”。

---

## 3. 保留 ReportDataPackage：完整证据层仍然必要

优化 Token 并不意味着删除完整结构化语义层。

`ReportDataPackage` 仍然负责保存：

- 测试元数据；
- 测试类型；
- 协议版本；
- 指标定义版本；
- 配置快照；
- 标量 Fact；
- 逐跳、逐步、周期 RecordSet；
- Series 描述；
- 左右侧；
- 顺序；
- 纳入统计状态；
- 排除原因；
- 缺失原因；
- 质量标记；
- Provenance；
- 原始数据引用。

它是**权威证据层**，不是默认 Prompt。

```text
TestReport
    ↓
ReportDataPackage
    ├── UI Adapter
    ├── Deterministic Analysis Suite
    └── Evidence Resolver
```

因此 UI 和 AI 共享同一个数据来源，但互不依赖：

```text
ReportDataPackage
    ├── UI ViewModel → 卡片 / 图表 / 表格 / 足迹
    └── AI Pipeline  → Insight / NarrativePlan / AnalysisPackage
```

UI 的中文名称、颜色、单位显示方式发生变化，不影响 AI。

---

## 4. 核心优化：Deterministic Analysis Suite

生成 `ReportDataPackage` 后，本地一次性执行所有适用于当前测试类型的低成本确定性分析。

### 4.1 纵跳分析器

第一版可以包含：

- `JumpSummaryAnalyzer`
- `JumpConsistencyAnalyzer`
- `EarlyLateAnalyzer`
- `BestAttemptAnalyzer`
- `OutlierInfluenceAnalyzer`
- `ContactFlightAnalyzer`
- `ExclusionInfluenceAnalyzer`
- `QualityAnalyzer`

可识别：

- 整体表现；
- 稳定性；
- 最佳试次；
- 前后阶段变化；
- 后程下降；
- 单个异常试次影响；
- 触地/腾空结构变化；
- 排除试次对总体结果的影响；
- 数据质量限制。

### 4.2 跑步机步态 / 跑步分析器

第一版可以包含：

- `MetricSummaryAnalyzer`
- `SideDifferenceAnalyzer`
- `SidePersistenceAnalyzer`
- `EarlyLateAnalyzer`
- `SegmentVariabilityAnalyzer`
- `OutlierInfluenceAnalyzer`
- `ExclusionInfluenceAnalyzer`
- `CycleQualityAnalyzer`
- `LongitudinalAnalyzer`
- `CohortAnalyzer`

可识别：

- 总体稳定性；
- 左右均值差异；
- 左右差异是否持续；
- 前后阶段变化；
- 后半程波动；
- 异常步影响；
- 排除记录影响；
- 不完整边界周期；
- 与个人历史的变化；
- 在团队分布中的位置。

这些分析器全部是普通 Python 程序，不调用 LLM。

对于几十到几百条步态记录，本地完成这些统计和规则判断的成本远低于一次远程模型调用。

---

## 5. InsightCandidate：把数值结果转换成“候选洞察”

各确定性 Analyzer 不生成自然语言报告，而统一生成 `InsightCandidate`。

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict


class InsightCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    insight_id: str

    insight_type: str
    metric_codes: tuple[str, ...]
    scope: str

    finding_code: str
    direction: str | None = None

    priority_score: float
    confidence_level: Literal[
        "limited",
        "suggestive",
        "supported",
        "strong"
    ]

    fact_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    quality_flag_ids: tuple[str, ...] = ()

    render_template_id: str | None = None
```

例如：

```json
{
  "insight_id": "ins_41AA",
  "insight_type": "temporal_variability",
  "metric_codes": ["contact_time"],
  "scope": "included_steps",
  "finding_code": "late_variability_higher",
  "direction": "increase",
  "priority_score": 0.84,
  "confidence_level": "supported",
  "fact_ids": [
    "f_contact_early_sd",
    "f_contact_late_sd"
  ],
  "evidence_refs": [
    "profile_contact_time_quartiles"
  ],
  "quality_flag_ids": []
}
```

Agent 不需要读取 46 步触地时间才能知道存在这一现象。

---

## 6. Insight Compiler：真正降低 Token 的核心

`Insight Compiler` 对所有 `InsightCandidate` 进行确定性筛选和排序。

它解决两个问题：

1. 完整数据很多，但哪些信息值得进入 Prompt？
2. 如何避免因为压缩而漏掉真正重要的局部趋势？

### 6.1 先全量筛查，再压缩

不要采用：

```text
先压缩数据
→ 再让 Agent 从摘要里发现趋势
```

因为摘要过程可能已经把趋势删除。

应该采用：

```text
完整数据
→ 确定性全量筛查
→ 得到候选洞察
→ 再压缩候选洞察
```

这一区别非常关键。

### 6.2 排序依据

可以定义：

```text
priority =
    effect_strength
  × evidence_quality
  × sample_reliability
  × domain_importance
  × novelty
```

第一版不必追求复杂公式，可以直接采用明确的优先级规则。

例如：

```text
critical quality issue
    >
strong temporal change
    >
persistent side difference
    >
large longitudinal change
    >
cohort position anomaly
    >
general stable metric
```

### 6.3 固定信息预算

例如每份报告最多进入 NarrativePlan：

- 2 个总体表现；
- 2 个重点变化；
- 1 个时序模式；
- 1 个左右差异；
- 1 个历史/团队比较；
- 必须出现的数据质量限制。

总计控制在约 5～8 个核心 Insight。

这样 Prompt 大小不会随着逐步记录数量线性增长。

---

## 7. InsightSnapshot

所有候选洞察可以保存成不可变快照：

```python
class InsightSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    report_package_id: str

    analysis_suite_version: str

    candidates: tuple[InsightCandidate, ...]

    source_digest: str
    snapshot_digest: str
```

它的价值是：

- Agent 不需要重复分析原始数据；
- 相同报告可以复用相同 Insight；
- 可以测试规则升级前后结果；
- 可以稳定重放；
- 后续调整语言模型不会改变底层分析事实。

---

## 8. NarrativePlan：真正发送给 LLM 的对象

LLM 默认不读取：

- 完整 `ReportDataPackage`；
- 完整逐步数组；
- 完整逐跳数组；
- 原始帧；
- 足迹数据；
- 所有历史记录；
- 全部 MetricCatalog；
- 所有 Tool 定义。

它只读取已经完成内容选择的 `NarrativePlan`。

### 示例

```json
{
  "report_id": "rpt_8F4K2M",
  "test_type": "treadmill_gait",

  "output_policy": {
    "language": "zh-CN",
    "max_sections": 4,
    "max_sentences_per_section": 3,
    "no_new_numbers": true,
    "no_new_formula": true,
    "no_diagnosis": true
  },

  "report_context": {
    "included_steps": 41,
    "quality_status": "usable_with_limits"
  },

  "sections": [
    {
      "section_code": "overall",
      "claim_ids": ["c1", "c2"]
    },
    {
      "section_code": "temporal",
      "claim_ids": ["c3"]
    },
    {
      "section_code": "asymmetry",
      "claim_ids": ["c4"]
    },
    {
      "section_code": "limitations",
      "claim_ids": ["c5"]
    }
  ],

  "claims": {
    "c1": {
      "meaning": "总体步频保持稳定",
      "strength": "supported",
      "fact_refs": ["f_cadence_mean", "f_cadence_cv"]
    },
    "c2": {
      "meaning": "步长整体波动较低",
      "strength": "supported",
      "fact_refs": ["f_step_length_cv"]
    },
    "c3": {
      "meaning": "后25%阶段触地时间波动高于前25%",
      "strength": "supported",
      "render_ref": "tpl_temporal_sd_001"
    },
    "c4": {
      "meaning": "左右步长存在差异，但未持续覆盖全部阶段",
      "strength": "suggestive",
      "render_ref": "tpl_side_partial_001"
    },
    "c5": {
      "meaning": "两个边界周期未纳入周期统计",
      "strength": "required_limit",
      "quality_refs": ["q_boundary_cycles"]
    }
  }
}
```

这个对象本质上已经回答了：

- 写什么；
- 不写什么；
- 哪些内容重要；
- 先写什么、后写什么；
- 每个结论证据在哪里；
- 哪些限制必须披露。

LLM 只负责：

- 跨维度综合；
- 避免机械重复；
- 形成自然段；
- 控制语言专业度；
- 生成流畅的运动测试分析表达。

---

## 9. 数值不交给 LLM 自由生成

高可信报告中，不建议让模型自由复制或重写关键数值。

使用 Fact Binding。

```python
class NumericBinding(BaseModel):
    placeholder: str
    fact_id: str
    format_code: str


class PlannedClaim(BaseModel):
    claim_id: str

    semantic_meaning: str
    text_template: str

    numeric_bindings: tuple[NumericBinding, ...]

    fact_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    strength: str
```

例如：

```text
后25%阶段触地时间标准差为 {late_sd}，
前25%阶段为 {early_sd}。
```

绑定：

```text
late_sd  → f_contact_late_sd
early_sd → f_contact_early_sd
```

最终由本地 `FactRenderer` 写入：

```text
后25%阶段触地时间标准差为 19 ms，
前25%阶段为 9 ms。
```

这样可以显著降低：

- 数字复制错误；
- 单位错误；
- 百分比重算错误；
- 小数位错误；
- 模型改变比较方向的风险。

---

## 10. 单一 Skill 设计

系统不需要多个互相调用的 Skill。

第一版只设计一个：

```text
compose_smart_analysis
```

固定工作流：

```text
1. 读取 NarrativePlan
2. 理解各 Claim 的关系
3. 按计划组织报告
4. 合并重复信息
5. 加入必要的限定表达
6. 输出结构化分析文本
```

### Skill 允许做

- 调整句式；
- 合并语义相近的 Claim；
- 增加必要过渡；
- 将时序、左右侧、纵向、横向结果进行语言综合；
- 根据 `strength` 调整声明强度；
- 控制篇幅。

### Skill 禁止做

- 自行重新计算数值；
- 自定义统计公式；
- 创造新的指标；
- 生成不存在的数字；
- 修改 Fact；
- 忽略 required quality limitation；
- 进行医学诊断；
- 从无证据的相关性推断因果关系。

### Tool 调用

默认生成流程中 **不进行多轮 Agent Tool Calling**。

所有常规确定性分析在 `Deterministic Analysis Suite` 中一次执行完成。

如果后续发现某些分析非常昂贵，可以由应用层根据测试类型和可用数据决定是否执行，而不是让 LLM 逐轮决定。

---

## 11. AnalysisPackage

LLM 输出不是最终可信结果，仍需要结构化 `AnalysisPackage`。

```python
class AnalysisClaim(BaseModel):
    claim_id: str

    text_template: str
    used_fact_ids: tuple[str, ...]
    used_insight_ids: tuple[str, ...]

    strength: str


class AnalysisPackage(BaseModel):
    analysis_id: str
    report_package_id: str
    insight_snapshot_id: str

    model_name: str
    skill_version: str
    narrative_plan_digest: str

    claims: tuple[AnalysisClaim, ...]

    validator_version: str
    validation_passed: bool
```

本地 Validator 检查：

- Fact 是否存在；
- 数值是否来自 Fact；
- 单位是否正确；
- 使用的 Insight 是否属于当前快照；
- 协议比较是否兼容；
- 样本量是否允许该声明；
- quality limitation 是否遗漏；
- 声明强度是否超过证据；
- 是否出现禁止推断；
- 是否出现无来源数字。

只有校验通过，结果才显示在报告固定智能分析区域。

---

## 12. 最终统一数据流

完整流程：

```text
┌───────────────────────────┐
│      Frozen TestReport    │
└──────────────┬────────────┘
               ↓
┌───────────────────────────┐
│     ReportDataPackage     │
│ 完整、可恢复、可追溯证据 │
└──────────────┬────────────┘
               ↓
┌───────────────────────────┐
│ Deterministic Analysis    │
│          Suite            │
│                           │
│ summary                   │
│ temporal                  │
│ side                      │
│ outlier                   │
│ exclusion                 │
│ quality                   │
│ longitudinal              │
│ cohort                    │
└──────────────┬────────────┘
               ↓
┌───────────────────────────┐
│      Insight Compiler     │
│                           │
│ 去重 / 排序 / 限额 / 过滤 │
└──────────────┬────────────┘
               ↓
┌───────────────────────────┐
│      InsightSnapshot      │
└──────────────┬────────────┘
               ↓
┌───────────────────────────┐
│       NarrativePlan       │
│ 约 5～8 个核心 Claim     │
└──────────────┬────────────┘
               ↓
┌───────────────────────────┐
│ DeepSeek Flash            │
│ 非思考模式 / 单次调用     │
└──────────────┬────────────┘
               ↓
┌───────────────────────────┐
│ FactRenderer + Validator  │
└──────────────┬────────────┘
               ↓
┌───────────────────────────┐
│      AnalysisPackage      │
└──────────────┬────────────┘
               ↓
           报告 UI
```

对用户而言始终只有：

```text
点击“智能分析”
        ↓
生成智能分析结果
```

内部架构复杂性不暴露给用户。

---

## 13. Token 与延迟控制

### 13.1 最大优化来自“减少模型任务”

真正应该减少的不是 JSON 字符，而是 LLM 需要完成的工作：

原方案：

```text
理解数据
+ 搜索重要信息
+ 决定分析方向
+ 请求计算
+ 重新理解结果
+ 决定是否继续
+ 综合
+ 写作
```

新方案：

```text
理解 5～8 个已验证 Insight
+ 综合
+ 写作
```

### 13.2 固定 Prompt 上限

第一版可设置：

```text
NarrativePlan:
- 最多 8 个核心 Claim
- 每个 Claim 最多 3 个 Fact 引用
- 最多 5 个 Quality Limitation
- 不包含完整序列
- 不包含原始帧
- 不包含无关指标
```

建议将模型输入控制在一个稳定范围，例如：

```text
系统 Prompt / Skill：约 800～1500 tokens
NarrativePlan：约 800～2000 tokens
输出：约 400～900 tokens
```

这些只是初始工程预算，应通过真实报告测试确定。

### 13.3 输出长度限制

智能分析区域不需要重新复述所有报告数据。

推荐固定结构：

```text
总体表现
主要变化与稳定性
左右 / 历史 / 团队中的重要发现
数据质量与解释限制
```

最终正文通常控制在约 300～600 中文字。

完整数值仍然存在于报告卡片、图表和表格中。

### 13.4 缓存

可以缓存：

- 固定 Skill；
- 指标定义；
- 输出 Schema；
- 测试类型公共说明；
- 相同 `InsightSnapshot` 对应的 `NarrativePlan`。

但缓存只是进一步优化。

**真正降低 Token 和延迟的核心是 Insight Compiler，而不是 Prompt Cache。**

---

## 14. 如何避免压缩后遗漏隐藏趋势

这是整个方案最重要的验证点。

不能指望一个均值摘要发现所有趋势。

解决方案不是把完整数组交给 LLM，而是对完整数据执行确定性 Screening。

至少建立以下测试模式：

### 时序

- 前后阶段均值变化；
- 后半程方差增加；
- 中途变化；
- 连续同方向变化；
- 局部异常。

### 左右侧

- 平均差异；
- 持续差异；
- 短暂差异；
- 某一阶段才出现的差异。

### 异常值

- 单个异常试次；
- 异常试次是否明显改变总体统计。

### 数据有效性

- 排除项是否改变结论；
- 缺失是否集中在特定阶段；
- 边界周期是否制造假趋势。

因此：

```text
完整数据
    ↓
确定性模式检测
    ↓
候选 Insight
    ↓
压缩
```

而不是：

```text
完整数据
    ↓
先压缩成均值
    ↓
让 LLM 猜是否有隐藏趋势
```

---

## 15. 与原方案的关系

### 继续保留

- `TestReport`
- `ReportDataPackage`
- `MetricCatalog`
- `Fact ID`
- `RecordSet`
- `Series ID`
- `QualityFlag`
- `Provenance`
- `AnalysisPackage`
- 协议兼容性校验
- 确定性横向 / 纵向 / 时序分析

### 新增

- `Deterministic Analysis Suite`
- `InsightCandidate`
- `InsightSnapshot`
- `InsightCompiler`
- `NarrativePlan`
- `FactRenderer`

### 删除或推迟

- Agent 首轮读取大型 `ReportManifest`
- 多轮 Tool Calling
- 多个可组合 Skill
- Skill 递归
- `report_triage` Agent
- `evidence_binding` Agent
- `analysis_stop_check` Agent
- 多 Agent 编排
- LLM 自我反思循环

`ReportManifest` 如果未来仍有调试、审计或其他需要，可以保留为内部结构，但它不应成为默认智能报告生成的 Prompt。

---

## 16. 第一版 MVP

### Phase 1：ReportDataPackage

完成：

```text
TestReport
→ ReportDataPackageBuilder
→ ReportRepository
```

验证：

- 字段覆盖率；
- 数值一致率；
- 顺序保持率；
- 左右侧保持率；
- inclusion/exclusion 状态保持率；
- 引用可解析率。

这些核心指标目标应为 100%。

### Phase 2：Deterministic Analysis Suite

先实现约 8～12 个高价值 Analyzer。

不追求高级统计。

优先覆盖：

- summary；
- early/late；
- segment variability；
- side difference；
- side persistence；
- outlier influence；
- exclusion influence；
- quality。

### Phase 3：Insight Compiler

实现：

- 去重；
- 优先级排序；
- Claim 数量上限；
- 必须披露的质量限制；
- Narrative section 分配。

### Phase 4：NarrativePlan + 单次 LLM

沿用现有 DeepSeek Flash 非思考模式。

只实现一个 Skill：

```text
compose_smart_analysis
```

### Phase 5：FactRenderer + Validator

首先保证：

- 无新数字；
- 数字引用正确；
- 单位正确；
- evidence 引用可解析；
- quality limitation 不遗漏；
- 禁止推断不出现。

---

## 17. 可量化验证方法

应至少比较：

```text
A. 完整 Report JSON → 单次 LLM
B. Manifest → 多轮 Tool Calling
C. Insight Compiler → NarrativePlan → 单次 LLM
D. 确定性模板
```

### 17.1 数据层指标

- Field Coverage Rate
- Numeric Equality Rate
- Order Preservation Rate
- Inclusion State Preservation Rate
- Evidence Resolution Rate
- Replay Consistency

### 17.2 分析正确性

构造带已知模式的测试数据：

- 后程波动增加；
- 前后阶段明显变化；
- 单个异常试次；
- 持续左右差异；
- 短暂左右差异；
- 排除项改变总体方向；
- 边界周期假趋势；
- 样本量不足；
- 历史协议不兼容。

计算：

```text
Hidden Pattern Recall
Hidden Pattern Precision
Numeric Accuracy
Unsupported Claim Rate
Quality Limitation Omission Rate
Protocol Misuse Rate
```

### 17.3 性能指标

记录：

```text
Input Tokens
Output Tokens
LLM Call Count
TTFT
Total Latency
Local Analysis Latency
```

### 17.4 MVP 目标

建议初始目标：

```text
数字正确率：100%
Evidence 引用可解析率：100%
禁止推断违规率：0%
关键质量限制遗漏率：0%
主要预定义隐藏模式召回率：≥95%
标准分析模型调用次数：1
相比完整 JSON 输入 Token：降低 ≥70%
```

隐藏模式召回率不应声称针对“任意模式”，而是针对系统明确声明支持的模式集合。

---

## 18. 最终设计原则

最终系统不应该是：

> “让一个很聪明的 Agent 阅读整个运动测试报告，然后自由决定怎样分析。”

而应该是：

> “让确定性系统完整理解数据结构并提前计算可验证事实，再让 LLM 对少量高价值事实进行受约束的跨维度综合和自然语言表达。”

最终职责分工：

```text
TestReport
    = 原始领域事实

ReportDataPackage
    = 无损语义证据层

Deterministic Analysis Suite
    = 数值分析与模式检测

Insight Compiler
    = 内容选择与报告规划

DeepSeek Flash
    = 综合、解释和语言实现

FactRenderer / Validator
    = 数值、证据和可信性控制

AnalysisPackage
    = 可追溯最终产物
```

这一架构同时满足：

- 单一用户入口；
- Token 可控；
- 输出速度快；
- 数值可靠；
- 隐藏趋势可发现；
- 证据可追溯；
- UI 与 AI 解耦；
- 可重放；
- 可测试；
- 后续可扩展纵向和团队分析。

---

# 参考资料

## 1. Operation-guided Neural Networks for High Fidelity Data-To-Text Generation

Feng Nie, Jinpeng Wang, Jin-Ge Yao, Rong Pan, Chin-Yew Lin. EMNLP 2018.

核心启示：对于需要计算或推理的 Data-to-Text 场景，可以先执行符号化操作，再让生成模型使用已经计算好的结果，从而提升事实忠实度。论文在体育数据集上进行了实验。

- ACL Anthology: https://aclanthology.org/D18-1422/
- PDF: https://aclanthology.org/D18-1422.pdf

## 2. Enhancing factualness and controllability of Data-to-Text Generation via data Views and constraints

Craig Thomson, Clement Rebuffel, Ehud Reiter, Laure Soulier, Somayajulu Sripada, Patrick Gallinari. INLG 2023.

核心启示：使用 Data Views 作为高层数据和文档规划单元，让模型主要负责 micro-planning 和 surface realization，而不是直接从全部多维数据中自行决定内容。

- ACL Anthology: https://aclanthology.org/2023.inlg-main.16/
- PDF: https://aclanthology.org/2023.inlg-main.16.pdf

## 3. Make Templates Smarter: A Template Based Data2Text System Powered by Text Stitch Model

Bingfeng Luo, Zuo Bai, Kunfeng Lai, Jianping Shen. Findings of EMNLP 2020.

核心启示：模板系统在事实忠实度和可控性方面具有优势，神经生成可以用于改善模板单元之间的自然衔接。适合“确定性事实 + AI 语言组织”的混合式架构。

- ACL Anthology: https://aclanthology.org/2020.findings-emnlp.94/
- PDF: https://aclanthology.org/2020.findings-emnlp.94.pdf

## 4. Input Matters: Evaluating Input Structure’s Impact on LLM Summaries of Sports Play-by-Play

Barkavi Sundararajan, Somayajulu Sripada, Ehud Reiter. INLG 2025.

核心启示：在体育逐事件数据摘要中，输入结构会显著影响事实错误率。论文比较了非结构化、行结构和 JSON 输入，JSON 输入的事实错误明显更少。这支持使用明确的结构化 NarrativePlan，而不是 UI 文本或自然语言拼接数据。

- ACL Anthology: https://aclanthology.org/2025.inlg-main.46/
- PDF: https://aclanthology.org/2025.inlg-main.46.pdf

## 5. Are Multi-Agents the new Pipeline Architecture for Data-to-Text Systems?

Chinonso Cynthia Osuji, Brian Timoney, Mark Andrade, Thiago Castro Ferreira, Brian Davis. INLG 2025.

核心启示：多 Agent 可以把 content ordering、text structuring、surface realization 和 guardrail 分工，但会显著增加系统编排复杂度。其结果说明多 Agent 是可行研究方向，但并不意味着简单的 Data-to-Text 系统必须采用多 Agent。因此本项目第一版不采用多 Agent。

- ACL Anthology: https://aclanthology.org/2025.inlg-main.33/
- PDF: https://aclanthology.org/2025.inlg-main.33.pdf

## 6. How to Make Neural Natural Language Generation as Reliable as Templates in Task-Oriented Dialogue

Henry Elder, Alexander O’Connor, Jennifer Foster. EMNLP 2020.

核心启示：在准确性优先的生成任务中，限制生成空间可以换取更高的语义可靠性；对于运动测试可信报告，可靠性应优先于语言多样性。

- ACL Anthology: https://aclanthology.org/2020.emnlp-main.230/
- PDF: https://aclanthology.org/2020.emnlp-main.230.pdf

## 7. RAG as a collapsed NLG pipeline

Adarsa Sivaprasad, Barkavi Sundararajan, David M. Howcroft. Symposium on Natural Language Generation Evaluations, 2026.

核心启示：经典 NLG pipeline 对理解现代生成系统的可控性仍然有价值；RAG 存在检索非确定性和上下文忠实度等问题。对于精确数值型运动测试数据，RAG 不应替代确定性结构化数据访问。

- ACL Anthology: https://aclanthology.org/2026.retroeval-main.5/
- PDF: https://aclanthology.org/2026.retroeval-main.5.pdf
