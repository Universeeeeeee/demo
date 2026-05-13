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