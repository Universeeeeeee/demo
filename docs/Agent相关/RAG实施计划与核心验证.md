# Iron_Jump 运动表现 RAG V1 实施与验证记录

## 1. 当前状态

V1 Deterministic RAG 已完成代码实现、检索基线、自动化 Generator/E2E Benchmark、`analysis-schema/4.0` 和报告 UI。2026-08-27 完成当前冻结版本的真实 DeepSeek Groundedness 逐条审查并生成受版本控制的发布产物，生产开关已通过 `knowledge/v1_release_gate.json` 开启。

固定链路：

```text
已验证测试 Claim
  → 确定性 QueryPlanner
  → metadata filter
  → SQLite FTS5 + Dense Retrieval
  → RRF Top-K Evidence
  → PydanticAI + DeepSeek（一次生成，retries=0）
  → RecommendationValidator
  → 确定性 Citation
  → analysis-schema/4.0
```

LLM 不决定是否检索、不改写 Query、不调用网页或数据库工具，也不能生成 URL、DOI 和 Citation。生成失败或校验失败不会影响原有确定性报告。

## 2. 架构来源

| 项目 | 采用内容 | 未采用内容 |
| --- | --- | --- |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) | 结构化来源与普通 Markdown 参考资料分离 | TypeScript 运行时和完整前端组件 |
| [LangChain Retrieval](https://docs.langchain.com/oss/python/langchain/retrieval) | 可预测的 2-step RAG 思路 | LangChain 抽象层 |
| [LlamaIndex Ingestion Pipeline](https://docs.llamaindex.ai/en/v0.10.17/module_guides/loading/ingestion_pipeline/root.html) | 文档 hash、增量缓存和不可变版本思路 | 完整框架 |
| [Haystack](https://docs.haystack.deepset.ai/docs/evaluation) | Retriever、Generator、端到端分层评测 | Pipeline 运行时 |
| [RAGFlow](https://github.com/infiniflow/ragflow) | 结构切片、人工检查、引用回放 | 服务端基础设施 |

项目继续使用 Python、Pydantic、SQLite、PydanticAI、FastEmbed、NumPy 和 pypdf，不依赖完整 RAG 框架。

## 3. 数据模型与增量摄取

核心扁平模型：

- `KnowledgeSource`
- `KnowledgeDocument`
- `DocumentVersion`
- `KnowledgeChunk`
- `KnowledgeQuerySpec`
- `LiteratureEvidence`
- `Citation`
- `Recommendation`
- `ValidatedRecommendationPackage`
- `RAGAudit`

ID 规则：

- `document_id` 表示稳定文档身份；版本由规范化原文 hash 对应的 `version_id` 管理。
- `chunk_id = sha256(document_id + chunker_version + logical_position + content_hash)`。
- `logical_position` 为 domain、规范化章节路径和章节内块序号。
- Embedding 缓存键为 `(content_hash, embedding_model_version)`。

SQLite 使用 sources、documents、document_versions、chunks、embeddings、三张核心 metadata 关联表、FTS 和 ingestion_runs。重复摄取不重算 Embedding；文档新版本只更新变化内容，并在事务中切换 active version。`python -m knowledge inspect-chunks` 可按来源、领域、指标和支持类型检查 Chunk。

## 4. 核心语料

完整目录在 `knowledge/sources.json`，共 19 项，其中 9 篇开放全文进入索引：

### 测量与方法

1. [纵跳腾空时间法测量误差](https://pmc.ncbi.nlm.nih.gov/articles/PMC5377563/)
2. [视频帧率与 CMJ 测量准确性](https://pmc.ncbi.nlm.nih.gov/articles/PMC10108745/)
3. [混合健康/卒中人群的步态设备一致性](https://pmc.ncbi.nlm.nih.gov/articles/PMC4106927/)——禁止用于 Recommendation。
4. [老年人步态评估指南](https://pmc.ncbi.nlm.nih.gov/articles/PMC5540886/)——仅定义/方法，禁止用于 Recommendation。
5. [健康青年 OPTOGait 效度与重测可靠性](https://pmc.ncbi.nlm.nih.gov/articles/PMC3927048/)
6. [跑步机跑步 OptoGait 一致性](https://pmc.ncbi.nlm.nih.gov/articles/PMC7739620/)
7. [跑步机与地面跑可比性系统综述](https://pmc.ncbi.nlm.nih.gov/articles/PMC7069922/)——解释/限制，不用于训练建议。

### 训练方向

8. [个体项目运动员增强式跳跃训练系统综述与 Meta-analysis](https://pmc.ncbi.nlm.nih.gov/articles/PMC7931718/)
9. [中长跑运动员力量训练与跑步经济性系统综述与 Meta-analysis](https://pmc.ncbi.nlm.nih.gov/articles/PMC11052887/)

商业书籍、授权不明确材料和仅有摘要的研究只保存书目元数据，不做全文 Embedding。临床、疾病、术后、康复、老年阈值和混合临床人群通过 population 与 recommendation_allowed 硬过滤排除。

## 5. 检索与基线

生产检索顺序：

1. `domain / metric_codes / population / support_type / recommendation_allowed` 硬过滤；
2. FTS5/BM25 Top 20；
3. Dense Top 20；
4. RRF `k=60`；
5. 每 Query 最多 6 个 Evidence，同一来源最多 2 个 Chunk。

`protocol` 只作为普通 metadata，不参与 V1 硬过滤。任何过滤后空结果都直接返回空，不允许自动放宽条件。

当前语料为 508 个 Chunk，`chunker/2.2` 使用 220/40 token 目标与重叠；训练方向只在 Abstract、Results、Discussion、Conclusion、Key Points 等承载结论的章节启用，Introduction/Background 确定性禁用 Recommendation，训练文献的 Methods 等章节同样禁用。冻结 30 问 baseline：

| 指标 | 结果 |
| --- | ---: |
| Recall@5 | 1.000 |
| Recall@10 | 1.000 |
| Precision@5 | 0.533 |
| MRR | 0.900 |
| nDCG@10 | 0.928 |

正式基线位于 `knowledge/retrieval_baseline.json`。当前五个启用场景的 Evidence Coverage 为 100%，metadata leakage 和禁止人群 leakage 均为 0，记录在 `knowledge/v1_support_benchmark.json`。

## 6. Generator、Validator 与 Citation

- DeepSeek 只接收已验证 Claim 和检索到的 Evidence 摘录。
- 每份报告最多三条一般行动建议。
- 禁止个性化组数、次数、负荷、强度、频率、医疗诊断、治疗、康复、伤病风险和无证据因果陈述。
- `generate once → validate → pass 输出 / fail 删除 + audit`，不 regenerate。
- Draft Schema 不包含 URL、DOI 或 Citation 字段。
- Citation ID、Evidence/Source/Document 映射、标题、URL、DOI 和定位全部由代码生成。
- `RAGAudit` 只保存版本、QuerySpec、Evidence ID/排名、Citation ID、校验结果、耗时、错误码和 digest，不复制 Prompt、Chunk 正文或原始模型输出。

## 7. Benchmark 与发布门

自动化部分包含 30 个固定端到端 Fixture，纵跳、步行、跑步各 10 个，覆盖：

- 正常 Recommendation 与 Citation；
- 无 Evidence；
- Generator 解析失败；
- 非法 Evidence 引用；
- 禁止训练剂量；
- 不匹配 population；
- 相同输入重复执行。

硬门槛已通过：无 Evidence 建议通过数为 0、非法引用通过数为 0、禁止内容通过数为 0、Citation 映射测试为 100%、metadata leakage 为 0、禁止人群 leakage 为 0。完整项目回归为 `717 passed, 12 subtests passed`。

2026-08-27 使用真实 DeepSeek 重新运行当前 `live-generator-groundedness/1.1` 的 30 个固定 Fixture：27 例正常完成，3 例按既定失败关闭策略降级且没有输出建议；Validator 放行 35 条建议、删除 40 条不合格候选建议，49 条 Citation 均可解析。逐条 Groundedness 审查未发现无 Evidence 支撑的已放行建议，因此 `unsupported_recommendation_count=0`。审查结果已通过 promotion 流程固化为 `knowledge/release_artifacts/sports-rag-v1-groundedness.json`，并由 release fingerprint 绑定当前 catalog、manifest、Prompt、Benchmark 与运行版本。

此前抽检发现的 Introduction 时态过期风险继续由 `chunker/2.2` 的确定性过滤控制：Introduction/Background 不得进入 Recommendation Evidence。运行中的 Generator 或解析失败仍只影响新增 RAG 字段，不影响原有确定性报告。

## 8. Schema 与 UI

`analysis-schema/4.0` 增量字段：

- `literature_evidence`
- `recommendations`
- `references`
- `references_markdown`
- `rag_audit`
- `prompt_content_digest` 作为可选完整 Prompt 内容审计摘要；旧包缺失时按
  `None` 兼容读取。
- Claim 保留 `citation_refs` 作为 V2 Grounding 通过后的正式入口；V1
  确定性锁定为空，不允许根据 Recommendation 引用做间接映射。

Report Service 的调用点固定在 ClaimValidator 之后、Renderer 之前。UI 已支持“循证行动建议”和“参考资料”，只渲染结构化 Citation 中经过 HTML 转义且协议为 HTTP(S) 的链接。当前 Release Gate 已通过，Worker 会在启动时构造生产 RAG Pipeline；工件或指纹后续发生漂移时仍会失败关闭并保留原有确定性分析。

正式发布使用“确定性 Citation 表面校验 + 冻结版本 + 人工
Groundedness 门”。本地生成的 `data/knowledge/groundedness_review.json`
不得直接用于生产 Gate；完成审查后必须通过 promotion 流程写入受版本控制的
`knowledge/release_artifacts/sports-rag-v1-groundedness.json`。Release
fingerprint 对 catalog、corpus manifest、检索/生成版本、实际 Prompt 内容和
冻结审查工件使用 canonical JSON 计算。Promotion 还要求完整覆盖冻结的
benchmark case 集，并校验 review 内记录的 catalog、manifest、Prompt 与
benchmark case 内容摘要；任一内容漂移均失败关闭。Gate 明确关闭时不提示
故障；若配置为启用但工件或指纹校验失败，则报告以 degraded 状态说明 RAG
不可用。

## 9. V2（未实现）

V2 只保留计划：Evidence Validator 判断证据不足时，全报告最多一次受控 Query Rewrite 和重新检索；生成后进行 Grounding/Citation Check，失败建议直接删除，不重新生成，不做开放式 Agent 循环。
