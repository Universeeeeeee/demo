---
name: md-writing
description: >
  Use this skill when editing, rewriting, or expanding Markdown documents,
  especially learn.md, plan.md, challenge.md, architecture.md, and README.md.
  The goal is to make the content clear, accurate, well-positioned, and directly
  usable in the target document.
---

# Markdown Writing Skill

## 1. Read Before Writing

Before editing a Markdown document, first check whether the beginning of the file contains writing constraints, such as:

- AI 编辑约束
- 写作要求
- 文档说明
- 本文定位
- 格式要求
- 注意事项

If these constraints exist, follow them first.

If there are no explicit constraints, infer the writing style from:

- file name
- document title
- existing headings
- existing paragraph style
- existing tables, lists, and code blocks

Do not change the document’s purpose.  
Do not expand content in a direction that does not match the original document.

---

## 2. Document Type Rules

Choose the writing approach according to the Markdown file type.

### 2.1 `learn.md`

Used for learning notes and interview preparation.

Focus on:

- concepts
- principles
- key points
- common interview questions
- follow-up questions
- review-friendly summaries

Writing style:

- Clear and easy to review.
- Prefer concise explanations over long textbook-style paragraphs.
- When writing interview content, use a spoken and structured style.
- Examples can be used when they help understanding.

Preferred formats:

- 一句话解释 + 关键点
- 面试说法 / 追问点 / 设计收益
- 概念说明 / 原理 / 示例 / 总结

---

### 2.2 `plan.md`

Used for future project development plans.

Focus on:

- development goals
- task breakdown
- implementation order
- dependencies
- risks
- TODOs

Writing style:

- Write as a plan, not as completed work.
- Keep tasks clear and actionable.
- Prefer step-by-step structure when describing implementation.
- Do not claim that something has already been implemented unless the document clearly says so.

Preferred formats:

- 目标
- 实现思路
- 开发步骤
- 依赖项
- 风险点
- TODO

---

### 2.3 `challenge.md`

Used for problems encountered during project development and their solutions.

Focus on:

- problem background
- symptoms
- causes
- solution
- result
- trade-offs
- lessons learned

Writing style:

- Explain the problem clearly.
- Separate confirmed causes from possible guesses.
- Explain why the solution works.
- Avoid turning one issue into a long general tutorial.

Preferred formats:

- 问题现象
- 原因分析
- 解决方案
- 最终结果
- 经验总结

---

### 2.4 `architecture.md`

Used for project architecture and design explanation.

Focus on:

- module responsibilities
- system structure
- request flow
- data flow
- design decisions
- dependencies
- trade-offs

Writing style:

- Keep module boundaries clear.
- Prefer workflows for process explanations.
- Prefer tables for comparisons.
- Explain design decisions only as far as the document context supports.

Preferred formats:

- 模块职责
- 核心流程
- 数据流转
- 设计取舍
- 方案对比
- 架构说明

---

### 2.5 `README.md`

Used as a classic GitHub README.

Focus on:

- what the project is
- what problems it solves
- main features
- tech stack
- quick start
- usage
- project structure
- configuration
- common issues

Writing style:

- Write for external readers.
- Prioritize clarity and usability.
- Avoid excessive internal implementation details.
- Do not invent install commands, environment variables, deployment steps, or features.

Common sections:

- Overview
- Features
- Tech Stack
- Quick Start
- Usage
- Project Structure
- Configuration
- Common Issues

---

### 2.6 `素材.md` / 毕业论文素材

用于整理毕业论文（工学/工程方向）的写作素材，按章节组织。

Focus on:

- 问题背景与动机
- 设计方案与架构描述
- 实现细节与关键技术点
- 优化过程与量化效果
- 设计决策的理由与取舍
- 与前人工作的对比与映射
- 测试策略与覆盖情况
- 未完成或待补充的部分

Writing style:

- 工科学术风格：客观、精确、克制。
- 用数据和对比表说话，避免"显著提升""大幅优化"等空洞形容词。
- 每一个设计决策必须附带 **为什么这样做**（设计理由），而不能只写 **做了什么**。
- 技术术语前后统一，不混用同义词（如不要一处写"采样"一处写"取样"）。
- 引用外部论文/方法时，标注论文名和会议/期刊（如 `ClarifyGPT (ACM FSE 2024)`），不写"某论文""有研究"。
- 框图用 ASCII art 绘制，标注数据流向和关键判断节点。
- 对比表以优化前/优化后的量化数据为主，必须有具体数值和单位。
- 探索过程（如多方案尝试）用时间顺序叙述，明确写出每个方案的 **做法、结果、失败原因**。
- 代码级细节（文件名、函数名、行号）可以出现，但仅限于说明关键设计点，不展开大段代码。

内容组织规则：

| 章节 | 素材定位 | 典型内容 |
|---|---|---|
| 第一章~第三章 | 背景/综述/目标 | 不涉及本项目实现，以引用外部文献为主 |
| 第四章 系统设计 | 架构层面 | 模块职责、数据流图、线程模型、设计模式选择 |
| 第五章 系统实现 | 实现层面 | 关键技术细节、优化过程、量化对比、设计决策 |
| 第六章 系统测试 | 验证层面 | 测试用例设计、覆盖率、测试结果分析 |
| 第七章 | 总结展望 | 不涉及具体实现细节 |

工程设计描述规则：

- 设计理由放在技术点之后，紧接在描述后面，通常以"设计理由："开头。
- 数据/配置流用 `→` 箭头串联，关键判断点用分支表示。
- 线程/进程模型必须标注：所属线程、通信方式、频率量级。
- 表结构（如模块职责表）必须包含：文件 | 职责 | 输入 | 输出 至少四列。
- 对比表必须标注对比维度，避免"方案 A vs 方案 B"式的空洞比较。

量化数据规则：

- 耗时数据必须标注测量条件和单位（如"首次调用冷启动 ~6s"而非"变快了"）。
- 优化效果用三列对比表：优化项 | 优化前 | 优化后 | 手段 | 实施位置。
- 效果汇总可以出现百分比，但前面必须有绝对值做锚点（如"20s → 5s (-75%)"）。
- 不得编造未实测的数据。如果某项数据没有测量，写"待测量"而非估算值。

学术引用规则：

- 论文方法放入本项目时，必须写清楚：原论文做什么 → 本项目如何适配 → 映射关系表。
- 映射关系表至少包含三列：原论文 | 本项目实现 | 对应代码位置。
- 不要直接把论文结论当成本项目的结论。区分"论文说的"和"本项目验证到的"。

禁止行为：

- 不要用"显然""众所周知""毫无疑问"等主观副词。
- 不要把 TODO 写成已完成。"待补充""待测量"必须保留在素材中。
- 不要用模糊的数量词（"多次""大幅""若干"），除非后面紧跟具体数字。
- 不要在素材中写"第一章引言""本章小结"等正文衔接语——素材是待加工原料，不是正文草稿。
- 不要为了凑内容把一个技术点拆成多个小节。一个技术点一个小节。

格式约定：

- 素材中的小节标题用临时编号（如 `5.x`），待正式排版时替换。
- 不确定性内容用"（待确认）"标注。
- 待补充内容用"（待补充）"标注。
- 章节底部可以有"待分类素材"暂存区，存放尚未归类的零散笔记。
- 每次写作会话结束后，在"待分类素材"下方追加日期和本次新增内容的清单。

---

## 3. Content Positioning Rules

Before adding content, decide where it belongs.

Do not append everything to the end of the file by default.

General placement rules:

| Content type | Suggested section |
|---|---|
| Concept | background / concept / learn section |
| Workflow | process / flow / architecture section |
| Task | plan / TODO section |
| Problem | challenge / troubleshooting section |
| Design reason | design / trade-off section |
| Comparison | comparison / options section |
| Usage | README usage / quick start section |
| Interview answer | interview / learn section |
| Architecture diagram | 论文第四章 / architecture section |
| Design rationale | 论文第四章~第五章 / design / trade-off section |
| Optimization process | 论文第五章 / challenge section |
| Quantitative comparison | 论文第五~六章 / plan section |
| Test case / coverage | 论文第六章 / test section |
| Paper-to-project mapping | 论文对应章节 / design section |

If related content already exists:

- extend the existing section
- merge repeated ideas
- keep useful original wording
- avoid creating duplicate headings

---

## 4. Detail Level Rules

Match the level of detail to the document type.

| File type | Detail level |
|---|---|
| `learn.md` | concise, review-friendly, interview-oriented |
| `plan.md` | task-oriented, clear, not overly detailed |
| `challenge.md` | enough detail to show problem-solving process |
| `architecture.md` | structured, focused on flow and design |
| `README.md` | concise, user-facing, easy to understand |
| `素材.md` | structured, quantitative, design-reasoning-oriented, cite sources |

Avoid:

- unrelated background
- excessive theory
- unnecessary long explanations
- fabricated implementation details
- fabricated metrics, scale, dates, or results
- over-expanding minor sections

---

## 5. Output Format Rules

When adding new content, prefer formats that are easy to read and paste into Markdown.

Common format choices:

### Workflow

Use arrows when describing a process:

```markdown
A
→ B
→ C
→ Result
```

### Concept

Use short explanations and key points:

```markdown
一句话解释：

...

关键点：

- ...
- ...
- ...
```

### Interview Answer

Use structured interview-style writing:

```markdown
面试说法：

...

追问点：

- ...
- ...

设计收益：

- ...
- ...
```

### Comparison

Use tables when comparing options:

```markdown
| 对比项 | 方案 A | 方案 B |
|---|---|---|
| 核心思路 |  |  |
| 优点 |  |  |
| 缺点 |  |  |
| 适用场景 |  |  |
```

### TODO

Use checklist format for tasks:

```markdown
- [ ] ...
- [ ] ...
- [ ] ...
```

### Architecture / Data Flow Diagram (论文素材用)

Use ASCII art with consistent indentation. Annotate key decision points and data direction:

```markdown
输入
  ↓
步骤 A（说明处理内容）
  ↓
┌─ 判断条件? ─────────────────┐
│ 分支 1：→ 处理 → 结果       │
│ 分支 2：→ 处理 → 结果       │
└─────────────────────────────┘
  ↓
最终输出
```

- Arrow `↓` marks data flow direction.
- Box `┌─┐` wraps branching logic.
- Annotations in Chinese, kept short.
- For thread models: annotate thread ownership, connection type, and frequency.

### Quantitative Comparison Table (论文素材用)

Always include before/after columns with concrete units. Add a "手段" column describing the method:

```markdown
| 优化项 | 优化前 | 优化后 | 手段 | 实施位置 |
|---|---|---|---|---|
| 首次对话耗时 | ~20s（含初始化 6s） | ~5s | 后台线程预热 | `gait_agent.py` L12-14 |
```

- Numbers must be measured, not estimated.
- Units required (s, ms, tokens, %, etc.).
- "实施位置" gives file + line for traceability.

### Paper-to-Project Mapping Table (论文素材用)

When adapting a published method to this project:

```markdown
| 原论文 | 本项目实现 | 对应代码位置 |
|---|---|---|
| 采样 N 个代码方案 | `asyncio.gather(N × agent.run())` | `_verify_config` L241-243 |
| 按测试输出聚类 | `_cluster_configs()` 按关键字段组合分组 | `_cluster_configs` L174-183 |
```

- Three columns minimum.
- "对应代码位置" pinpoints function + line.
- Use "适配" not "等同于" — don't claim equivalence.

### Module Responsibility Table (论文素材用)

For architecture sections, describe each module boundary:

```markdown
| 文件 | 职责 | 输入 | 输出 |
|---|---|---|---|
| `gait_agent.py` | Facade 门面，模式路由 | `AthleteProfile` | `TestConfig` |
```

- "职责" describes what, not how.
- "输入/输出" uses type names, not variable names.

### Optimization Exploration Narrative (论文素材用)

When describing a multi-attempt process, use chronological order:

```markdown
**第 N 方案（方案名）**：做法。结果（成功/失败）。原因分析。

排除过程：验证了 X → 排除了 Y → 问题收敛于 Z。

**最终方案**：做法 + 通过结论。
```

- Each attempt: approach → result → failure reason.
- Ruled-out hypotheses demonstrate rigor — keep them.
- Let the reader understand why simpler approaches were insufficient.

---

## 6. Markdown Style Rules

- Keep heading levels consistent.
- Use clear and specific headings.
- Keep paragraphs short.
- Use bullet points for key information.
- Use numbered lists for ordered steps.
- Use tables for comparisons.
- Use code blocks for commands, config, pseudocode, logs, or examples.
- Specify code block language when useful.
- Match the language style of the original document.
- Avoid filler expressions such as “简单来说”, “众所周知”, “非常重要”.

---

## 7. Accuracy Rules

Do not invent facts.

Avoid unsupported claims about:

- technologies used
- implementation details
- performance numbers
- user scale
- deployment setup
- security guarantees
- completed features

If the document does not provide enough information, write conservatively.

For example:

```markdown
如果当前项目采用该机制，可以这样描述：
```

or:

```markdown
当前文档未说明具体实现，因此这里只从设计层面描述。
```

---

## 8. Final Checklist

Before outputting Markdown, check:

- Have I followed the document’s own writing constraints?
- Have I identified the document type?
- Is the content placed in the right section?
- Is the heading level consistent?
- Is the detail level appropriate?
- Is the format easy to read?
- Have I avoided unsupported assumptions?
- Can the content be pasted directly into the target document?

For `素材.md` specifically, also check:

- 每个设计决策是否附带了设计理由？
- 量化数据是否都有具体数值和单位？
- 对比表是否包含优化前/优化后/手段三列？
- 框图中的箭头和分支是否标注了含义？
- 技术术语全文是否统一（不存在同一概念多个叫法）？
- 是否有未完成的 TODO 或"待补充"被误删？
- 是否存在"大幅""显著""若干"等模糊量化词？
- 是否存在"第一章引言""本章小结"等正文衔接语？
- 待分类素材底部是否追加了本次会话的日期和内容清单？