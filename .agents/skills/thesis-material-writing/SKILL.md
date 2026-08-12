---
name: thesis-material-writing
description: Edit, draft, reorganize, or review Chinese graduation-thesis material for Iron_Jump, especially 素材.md or text intended to be pasted into it. Use for any request that adds project progress, architecture, implementation, experiments, results, limitations, or academic prose to the thesis material, even when the user does not explicitly name this skill.
---

# Thesis Material Writing

## Required reading

Before drafting or editing thesis material:

1. Read `writing.md` completely.
2. Read `素材.md` completely, or at minimum the entire target chapter plus the headings of the full file.
3. Inspect the current code, test output, or source document supporting every new technical claim.
4. Do not edit until these checks are complete.

## Select content

- State the system's current capabilities and verified results directly.
- Do not narrate how a feature evolved from an earlier version unless the development process itself is the research subject.
- Exclude Git history, branches, task completion records, routine dependency fixes, minor UI adjustments, and other project-management details unless they affect the research method or result.
- Preserve the existing chapter structure. Put system design in Chapter 4, key implementation in Chapter 5, and validation methods and results in Chapter 6.
- Add content to an existing related section instead of creating a duplicate heading.

Write `系统支持纵跳测试、跑步机步态测试和跑步机跑步测试。`

Do not write `系统已由单一纵跳测试扩展为同时支持……`

## Use natural academic Chinese

- Write objective, restrained engineering prose that may be reused in the thesis after factual review.
- Give each paragraph one clear purpose. Let paragraph length follow the content; do not force sections or paragraphs into matching shapes.
- Integrate causes, constraints, and consequences into the surrounding sentences. Do not append a templated explanation to every technical point.
- Prefer direct statements over slogans, symmetrical catchphrases, summary labels, or conversational explanations.
- Use tables and diagrams only when they make relationships or measured comparisons clearer than prose.
- Do not manufacture transitions or conclusions merely to make the text look complete.

Avoid these patterns:

- `设计理由：`
- `关键边界：`
- `一句话解释：` or `一句话总结：`
- `当前阶段结果表明……` without immediately naming the measured result
- `系统采用“……”的设计`
- slogan-like contrasts such as `光栅负责时间，视觉负责语义`
- unsupported words such as `显著`、`大幅`、`有效提升`、`充分证明`

Instead of writing a separate `设计理由` paragraph, integrate the reasoning:

`触地和离地时间由光电传感器确定。相机帧率和图像处理延迟限制了视觉计时精度，因此视觉结果仅用于补充左右脚信息，不参与修改触地时间。`

## Keep terminology consistent

- Use `红外光电传感器` at the first formal mention and `光电传感器` afterwards.
- Do not use `光栅` in thesis prose except when quoting a source or identifying an unchanged legacy code term.
- Prefer Chinese test names in prose: `纵跳测试`、`跑步机步态测试`、`跑步机跑步测试`. Add code identifiers only when implementation traceability is necessary.
- Use `触地`、`离地`、`腾空`、`步态周期`、`支撑相` and `摆动相` consistently with the project parameter documents.
- Minimize quotation marks. Use them only for direct quotations, official labels, code values, or terms that genuinely require distinction.

## Protect evidence boundaries

- Separate implementation status, automated verification, synthetic-data validation, device testing, and human ground-truth validation.
- Report a metric only with its sample count, unit, test condition, and applicable scope when available.
- Never convert repeated model output into accuracy without an independent ground-truth label.
- Do not infer experimental performance from code structure or passing unit tests.
- Mark missing evidence as `待测量` or `待验证`; do not estimate it.
- Keep limitations adjacent to the result they constrain rather than collecting generic disclaimers at the end.

## Edit surgically

- Modify only the requested thesis sections.
- Preserve useful existing wording and merge overlapping content.
- Do not turn `素材.md` into a project plan, README, development log, or finished thesis chapter.
- Keep temporary section numbers such as `4.x` and `5.x` until the formal outline is fixed.
- Do not add citations that have not been checked against the original source.

## Final check

Before finishing, verify all of the following:

- The text describes current facts rather than development history.
- The prose can stand on its own without labels such as `设计理由` or `关键边界`.
- `光电传感器` is used consistently and `光栅` has not slipped into thesis prose.
- Quotation marks, colons, headings, tables, and diagrams are necessary rather than decorative.
- Every number has a source and an evidence boundary.
- No unverified result is presented as accuracy, reliability, or improvement.
- Paragraph lengths and sentence structures follow the logic instead of a repeated template.
