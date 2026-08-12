# Iron_Jump Report Agent MVP Implementation Record

> 历史稿：本文件记录三工具架构实施前的任务拆分，不再作为当前架构或论文材料来源。当前架构以 `ReportAgentArchitecture_0808.md` v3.0 和代码中的 `SequentialAnalysisLoop`、`ActionValidator`、`AnalysisStateReducer` 为准。

> 状态：MVP 已完成；本文由实施前计划转为实现追踪记录。
> 架构依据：`ReportAgentArchitecture_0808.md`及其“完整修订计划（修订版）”。当两者存在冲突时，以修订版已经确认的职责边界为准。
> MVP范围：完成本次测试记录范围内的智能分析，即时序、左右侧、跨指标及质量/排除敏感性综合。个人历史纵向比较和团队横向比较只建立授权接口与拒绝路径，不实现实际比较。
> 实施约束：不修改确定性测试计算，不让Agent执行正式算术、开放SQL、任意Python或未注册算法。

## 0. 2026-08-10 实施结论

- Phase 0～7 的生产模块、确定性测试、Fake Agent 端到端测试、报告 UI 和真实模型合成 Benchmark 均已落地。
- 实际代码按 `agent/common/`、`agent/config/`、`agent/report/`、`reporting/` 和单 `agent/worker.py` 路由组织。
- Report Agent 生产默认采用 B：AnalysisSketch + Compact Series；Screening Cues 和 Replan 保留但默认关闭。
- 固定 12 类合成案例每类运行 3 次：B 为 `35/36` 有效，Expected Predicate Recall 为 `0.879`；D Recall 相同但没有实际触发 Replan。
- Benchmark 没有读取正式运动员数据库；结果只支持工程架构可行性，不支持真实训练或医学有效性。
- 该阶段最终由单步序贯循环取代；2026-08-12 全量回归为 `659 passed`、`12 subtests passed`。
- 当前未完成：个人历史纵向比较、团队横向比较、真实运动员专家标注实验、知识 RAG 和任何训练/医学建议。

下文保留原任务拆分、接口和验收条件，用于追溯实现来源；其中“实施前”“将新增”等措辞应按历史计划理解，不再表示当前代码状态。

---

## 1. 当前代码基线

当前`agent/`只实现测试前参数配置：

- `agent/llm_agent.py`包含PydanticAI参数配置Agent、模型Provider创建、Prompt加载、ClarifyGPT多采样和对话历史；
- `agent/gait_agent.py`缓存不同测试类型的`LLMConfigAgent`并封装离线规则与在线对话；
- `agent/rule_engine.py`实现纵跳参数的离线规则推荐；
- `agent/llm_worker.py`通过单一HTTP Worker暴露`/chat`、`/chat_stream`、`/reset`；
- `ui/llm_client.py`负责Worker进程、健康检查和HTTP请求；
- `ReportView.load_report(report)`只接收报告对象，不包含可供Worker查询的`session_id`；
- `SubjectStore`已保存`subject_id`、`team_id`、配置快照、受试者快照、团队快照和完整`report_detail_json`，并能按会话ID、受试者和团队读取记录；
- `JumpTestReport`、`TreadmillGaitReport`和`TreadmillRunningReport`已经包含构建本次记录语义数据层所需的主要逐跳、逐步、周期、纳入状态和质量字段；旧`GaitTestReport`缺少统一行级质量语义，不纳入Report Agent MVP。

实施前相关回归基线：

```text
Agent、Worker Client、SubjectStore及UI相关选定测试：77 passed
其中UI测试需设置：QT_QPA_PLATFORM=offscreen
未设置offscreen时：52 passed，25项因无可用屏幕导致dayu_widgets DPI初始化失败
```

该测试结果只作为实施前代码基线，不表示Report Agent能力已经实现或验证。

---

## 2. MVP完成定义

MVP完成后，联网状态下用户在报告页点击唯一的“智能分析”入口，系统使用当前会话ID从本地数据库重建不可变报告快照，构建结构化观察数据。Report Agent提出1～3个分析问题，生成小型计划，由确定性Analysis Kernel批量验证；通过Fact、Predicate和权限校验的结果写入独立分析运行记录，并显示在报告固定区域。最多一次 Replan 的能力已经实现，但根据消融结果生产默认设为 0；只有专门实验显式开启时才进入第二调查周期。

MVP必须满足：

1. 测试前Config Agent行为不因目录调整发生变化；
2. UI、Agent和确定性分析共同依赖独立`reporting/`业务层，`reporting/`不得依赖`agent/`；
3. Agent默认只能访问本次会话数据；
4. Agent不能声明权限要求，系统根据`operator + data_scope`推导权限；
5. 已有`ScalarFact`可直接支持描述性Claim，派生判断必须绑定Kernel证据；
6. Screening Cue只能用于提出问题，不能直接作为Claim Evidence；
7. 每轮最多3个Agent可见语义节点，Kernel内部子计算不受该数量限制但受成本预算约束；
8. 执行器最多支持两个调查周期、一次Replan；生产默认关闭Replan；
9. 最终Claim只允许MVP Predicate白名单并通过确定性Validator；
10. 离线、Worker不可用、会话未持久化或测试类型不受支持时，不显示智能分析入口和结果区域。

---

## 3. 目标目录与依赖方向

```text
agent/
├── __init__.py
├── worker.py
├── config/
│   ├── __init__.py
│   ├── agent.py
│   ├── models.py
│   ├── rule_engine.py
│   ├── service.py
│   └── prompts/
│       ├── __init__.py
│       ├── jump.md
│       ├── treadmill_gait.md
│       └── treadmill_running.md
├── report/
│   ├── __init__.py
│   ├── agent.py
│   ├── models.py
│   ├── tools.py
│   ├── analysis_loop.py
│   ├── service.py
│   └── prompts/
│       ├── __init__.py
│       └── system.md
└── common/
    ├── __init__.py
    └── model_provider.py

reporting/
├── __init__.py
├── models.py
├── metric_catalog.py
├── builders.py
├── observation.py
├── repository.py
├── kernel.py
├── validators.py
└── renderer.py
```

依赖方向：

```text
UI ───────────────────────────────→ reporting
UI → AgentWorkerClient → agent/worker.py
agent/config ─────────────────────→ agent/common
agent/report ─────────────────────→ agent/common
agent/report ─────────────────────→ reporting
reporting ────────────────────────→ config.test_report / data.subject_store

禁止：reporting → agent
禁止：UI → agent.report.agent / Prompt
禁止：agent.report → QWidget
```

`agent/common/logging.py`不进入MVP。现有标准`logging`继续使用；只有形成跨Config、Report、Tool Run的统一遥测协议后，才考虑增加`telemetry.py`。现有诊断脚本和独立测试UI不在本次迁移范围内，待生产模块稳定后单独整理。

### 3.1 与候选`agent/`目录的落地差异

本计划保留候选目录的核心边界：`config/`负责测试前配置，`report/`负责报告Agent编排，`common/`只放真正共享的基础能力。结合现有代码与架构依赖，作以下最小调整：

- `agent/worker.py`位于两个业务包之外，因为它同时承载Config与Report路由，任何一方都不应拥有它；
- Prompt继续使用`prompts/`资源目录及Markdown正文，不合并成单个`prompts.py`，以保留现有加载方式和独立版本标识；
- 现有确定性`rule_engine.py`保留在`agent/config/`，不混入Report Agent；
- `agent/report/service.py`作为Worker调用的单一用例入口，避免Worker直接组装Repository、Loop和Validator；
- 新增独立`reporting/`，因为ReportDataPackage、Observation、Kernel、Validator和Renderer同时服务UI与Agent，放入`agent/report/`会迫使UI依赖Agent业务包；
- 暂不创建`agent/common/logging.py`，避免仅为目录对称增加无实际共享协议的包装层。

这些调整不改变用户产品上只有一个“智能分析”，也不把Report Agent拆成多Agent或多Worker。

---

## 4. Traceability Matrix

| ID | 架构要求 | 实施任务 | 测试/验收项 |
|---|---|---|---|
| AR-01 | Config Agent与Report Agent解耦，只共享模型Provider和Worker运行基础设施 | T0.1、T0.2、T0.3 | 现有Config回归通过；UI导入不加载Report Agent或PydanticAI重模块 |
| AR-02 | 单Worker按业务路由Config与Report，请求状态和锁互相隔离 | T0.3、T5.1 | 旧配置路由兼容；报告请求不修改配置对话历史；两类锁独立 |
| AR-03 | 不可变TestReport继续作为事实源，Agent语义层独立于UI | T1.1～T1.3 | 三类报告转换前后深度序列化一致；UI不解析Agent Prompt |
| AR-04 | RecordSet保持行级顺序、侧别、时间、纳入/排除和指标对应关系，Series只是投影 | T1.1、T1.2 | Fixture字段覆盖、顺序保持、多指标对齐和Series回查100%通过 |
| AR-05 | Missing、Inclusion、Quality、单位、版本和Provenance显式表示，稳定ID可重放 | T1.1～T1.4 | 同一快照重复构建得到相同ID与digest；全部引用可解析 |
| AR-06 | 数据可用性与用户授权分离，用户决定可访问数据域 | T1.3、T2.1、T3.2、T5.2 | 未授权纵向/团队节点拒绝，Repository Spy确认无外部明细查询 |
| AR-07 | 产品只有一个“智能分析”，联网显示、离线隐藏，用户点击后才消耗模型Token | T6.1～T6.4 | 加载报告不触发分析；点击只产生一次请求；不可用时入口与结果区隐藏 |
| AR-08 | ReportManifest只保留导航元数据；Agent首轮输入为Analytical Observation Layer，而非UI文本或仅Manifest | T1.1、T1.2、T2.1～T2.3 | Manifest引用可解析；Observation含Manifest上下文、Fact、Sketch、Compact Series、Quality和辅助Cue |
| AR-09 | Screening Cue只是辅助线索，不能支持最终Claim | T2.2、T4.3、T4.4 | 仅引用Cue的Claim被拒绝；无Cue消融仍可生成分析问题 |
| AR-10 | 直接事实可绑定ScalarFact；趋势、比较、关系、持续性必须经Kernel验证 | T1.2、T3.3、T4.3、T4.4 | 描述性Claim可直接绑定Fact；派生Claim缺少Kernel Evidence时拒绝 |
| AR-11 | Agent不填写required_scope，权限由OperatorRegistry根据operator和data_scope推导 | T3.1、T3.2 | AnalysisQuestion无权限字段；伪造权限不能绕过Validator |
| AR-12 | Agent-level Operator与Kernel Primitive分离；每轮最多3个主要节点 | T3.1～T3.3、T4.2 | 一个语义节点可执行多个内部步骤；第4个主要节点被拒绝 |
| AR-13 | MVP采用Small Plan批量执行，最多一次Replan；长期保留Bounded Hypothesis Loop | T4.1、T4.2 | 充分证据一轮结束；冲突最多两轮；不存在第三轮或无限Tool Loop |
| AR-14 | MVP支持temporal × side × cross-metric × quality/exclusion综合 | T2.2、T3.3、T4.3 | 固定合成数据覆盖五类组合场景，Kernel结果与独立期望一致 |
| AR-15 | 最终输出为结构化Claim，数字与MVP Predicate白名单绑定 | T4.3、T4.4 | 白名单外Predicate拒绝；最终数值只由Renderer注入 |
| AR-16 | Claim Validator检查Fact、Tool Run、单位、权限、质量、样本量和禁止声明 | T4.4 | 未知数字、快照错配、越权、因果和医学诊断均被拒绝 |
| AR-17 | 横向/纵向架构从第一天预留，但MVP不读取外部明细 | T1.3、T3.1、T3.2 | scope字段存在；对应Operator禁用；Prompt不含外部明细 |
| AR-18 | AnalysisPackage、Tool Run和快照信息可保存、重开和审计 | T1.4、T4.5、T6.3 | 分析运行可按session_id读取；失败运行不冒充有效结果 |
| AR-19 | 分层读取和Token预算；不向模型发送完整历史、团队、原始帧或无限序列 | T2.2、T4.1、T5.2 | Observation序列上限、截取策略及Prompt大小均有记录 |
| AR-20 | MVP不引入Graph、Multi-Agent、RAG、Vector DB、任意SQL/Python和高级变化点算法 | 所有任务的“不做”条目 | 最终代码搜索、依赖检查和接口审查不得出现相应执行入口 |

---

## 5. Phase依赖关系

```text
Phase 0：Agent目录与Config基线重构
        ↓
Phase 1：ReportDataPackage与Repository
        ↓
Phase 2：Analytical Observation Layer
        ↓
Phase 3：OperatorRegistry、Kernel与PlanValidator
        ↓
Phase 4：Report Agent、Bounded Loop与可信输出
        ↓
Phase 5：单Worker报告协议与持久化联调
        ↓
Phase 6：报告UI集成
        ↓
Phase 7：端到端验收与Benchmark
```

Phase 0只改变模块位置和公共入口，不改变Config Agent行为。Phase 1～3必须全部通过纯确定性测试后，才能接入真实模型。Phase 4使用Fake Agent完成Loop测试后，才能进入Worker和UI联调。

---

## 6. Phase 0：Agent目录与Config基线重构

### T0.1 提取共享Model Provider

**文件**

- 新建`agent/common/__init__.py`
- 新建`agent/common/model_provider.py`
- 修改迁移后的`agent/config/agent.py`

**接口**

```python
@dataclass(frozen=True)
class ModelProviderSettings:
    base_url: str
    api_key: str
    model_name: str = "deepseek-v4-flash"

def load_model_provider_settings() -> ModelProviderSettings: ...

def build_chat_model(
    http_client: httpx.AsyncClient,
    settings: ModelProviderSettings | None = None,
) -> OpenAIChatModel: ...

def default_model_settings() -> dict: ...
```

`build_chat_model`只构造模型与Provider，不构造业务Agent，不保存历史，不加载Prompt。

**测试**

- 新建`tests/test_agent_model_provider.py`，覆盖`.env`缺失、显式Settings注入、模型名称和禁用thinking设置；
- 更新`tests/test_llm_agent_regressions.py`，通过注入Fake模型保持无网络测试。

**验收标准**

- Config Agent所有现有回归行为不变；
- 导入`agent.common.model_provider`不发起网络请求；
- Config和Report可以复用模型构造逻辑，但各自创建业务Agent。

**明确不做**

- 不共享Config与Report Prompt、对话历史或Output Schema；
- 不改变ClarifyGPT采样次数、聚类逻辑、超时和重试策略；
- 不新增通用日志包装层。

### T0.2 迁移Config Agent生产模块

**文件映射**

```text
agent/llm_agent.py      → agent/config/agent.py
agent/models.py         → agent/config/models.py
agent/rule_engine.py    → agent/config/rule_engine.py
agent/gait_agent.py     → agent/config/service.py
agent/prompts/*.md      → agent/config/prompts/*.md
```

更新`agent/__init__.py`、`ui/views/agent_config_panel.py`和对应测试导入。`ConfigService`替代`GaitAgent`作为Worker内部配置门面：

**接口**

```python
class ConfigService:
    def warmup(self, mode: str = "jump") -> None: ...
    def chat(self, message: str, profile: AthleteProfile, mode: str) -> tuple[AnyTestConfig | None, str]: ...
    def chat_stream(self, message: str, profile: AthleteProfile, mode: str, on_chunk) -> tuple[AnyTestConfig | None, str]: ...
    def reset(self) -> None: ...
    def configure_offline(self, test_type: str, profile: AthleteProfile) -> TestConfig: ...
```

**测试**

- 更新`tests/test_llm_agent_regressions.py`、`tests/test_llm_test_config.py`、`tests/test_rule_engine.py`、`tests/test_agent_config_panel.py`、`tests/test_agent_import_boundary.py`；
- 保留三种测试类型的Agent缓存、当前配置查询、流式输出和离线规则测试。

**验收标准**

- 迁移前Config相关测试全部通过；
- UI进程导入`AgentConfigPanel`时不导入`agent.config.agent`和PydanticAI模型运行模块；
- Markdown Prompt内容不改写，仅调整加载路径。

**明确不做**

- 不重写Config Agent业务逻辑；
- 不拆分现有431行配置模型；
- 不移动`agent_test_ui.py`、`diagnose_latency.py`和`web_search_mcp.py`。

### T0.3 将Worker调整为单进程分路由容器

**文件**

- `agent/llm_worker.py`迁移为`agent/worker.py`
- 修改`ui/llm_client.py`
- 修改`ui/main_window.py`中的Worker脚本路径

**接口**

**配置路由**

```text
POST /config/chat
POST /config/chat_stream
POST /config/reset
```

迁移期保留：

```text
POST /chat        → /config/chat
POST /chat_stream → /config/chat_stream
POST /reset       → /config/reset
```

Worker建立独立`_config_lock`和后续`_report_lock`，不得使用同一业务状态对象。

**测试**

- 新建`tests/test_agent_worker_routes.py`，直接调用Handler/Service替身验证路由；
- 更新`tests/test_llm_client.py`和`tests/test_main_window_navigation.py`；
- 验证旧配置路由与新路由返回相同Schema。

**验收标准**

- Worker健康检查、PID端口文件、空闲退出和关闭流程保持可用；
- Config请求与Report请求使用不同锁和Service；
- Phase 0结束时尚未实现的`/report/analyze`返回明确的404或`not_implemented`，不得伪造分析。

**明确不做**

- 不拆成两个Worker进程；
- 不改为Web框架、WebSocket或任务队列；
- 不改变现有SSE配置流式协议。

---

## 7. Phase 1：ReportDataPackage与Repository

### T1.1 定义语义证据模型和Metric Catalog

**文件**

- 新建`reporting/__init__.py`
- 新建`reporting/models.py`
- 新建`reporting/metric_catalog.py`

**核心类型**

```text
ReportContextInput
ReportMetadata
ReportManifest
MetricDefinition
ScalarFact
QualityFlag
RecordStatus
RecordSet
RecordSetDescriptor
SeriesDescriptor
ProvenanceRecord
ToolRunRecord
JumpPayload
TreadmillGaitPayload
TreadmillRunPayload
ReportDataPackage
DataScopeAvailability
DataAccessScope
AnalysisCapability
```

`DataAccessScope.current_session`固定为`True`；MVP请求中`longitudinal`和`cohort`必须为`False`。MetricDefinition增加`numeric_tolerance`，仅用于确定性方向判断，不表示临床或训练意义阈值。

**测试**

- 新建`tests/test_reporting_models.py`；
- 验证Pydantic discriminated union、Missing/Invalid状态、单位和Metric Catalog唯一性；
- 验证`DataAccessScope(current_session=False)`被Schema拒绝。

**验收标准**

- 三类测试指标均有唯一`metric_code`、规范单位、适用记录类型和数值容差；
-`NaN`、无限值和缺少原因的missing Fact不能进入Package；
- `reporting.models`不导入Qt或PydanticAI。

**明确不做**

- 不加入训练建议、医学阈值和“越高越好”结论；
- 不建立RDF Provenance；
- 不支持旧`GaitTestReport`分析。

### T1.2 实现三类ReportDataPackage Builder

**文件**

- 新建`reporting/builders.py`
- 只读取`config/test_report.py`、`config/treadmill_report.py`的现有不可变对象

**接口**

```python
class ReportDataPackageBuilder:
    def build(
        self,
        report: JumpTestReport | TreadmillGaitReport | TreadmillRunningReport,
        context: ReportContextInput,
    ) -> ReportDataPackage: ...

class ReportManifestBuilder:
    def build(self, package: ReportDataPackage) -> ReportManifest: ...
```

构建规则：

- 纵跳以`jump_results`为权威RecordSet，旧存档缺少该字段时使用现有反序列化兼容结果；
- 跑步机分别建立`step`和`gait_cycle` RecordSet；
- 原始帧、足迹帧不进入Package，只保存可解析引用或`not_collected`状态；
- `metric_summaries`等现有确定性摘要映射为`ScalarFact`；
- `ReportManifest`只保存Package/RecordSet/Series/Fact/Quality的稳定引用、记录规模和可用维度，不保存Screening Cue、趋势判断或完整序列；
- Builder不重新计算现有正式指标，只进行结构转换和完整性校验；
- Stable ID由`package_id + semantic identity`生成UUIDv5或SHA-256截断值；
- Package digest基于规范化JSON生成。

**测试**

- 新建`tests/test_report_package_builder.py`；
- 为纵跳、跑步机步态、跑步机跑步各建立正常、缺失、排除和质量标记Fixture；
- 检查RecordSet行顺序、侧别、纳入状态、多指标对齐、Fact数值、单位及Manifest引用；
- 对相同输入重复构建，验证ID和digest一致；
- 传入`GaitTestReport`时返回`UnsupportedReportTypeError`。

**验收标准**

- Fixture中所有计划字段覆盖率100%；
- 所有Record、Series、Fact、Quality及Manifest引用可解析；
- Builder执行前后原TestReport深度序列化结果相同；
- 不把真实0值转换成missing，也不把missing转换成0。

**明确不做**

- 不修改`TestReport`字段；
- 不重新计算基础运动学指标；
- 不把1000Hz原始帧复制进Package；
- 不执行横向或纵向比较。

### T1.3 实现ReportRepository和数据范围可用性

**文件**

- 新建`reporting/repository.py`
- 必要时只为`data/subject_store.py`补充公开只读查询，不改变现有会话写入语义

**接口**

```python
class ReportRepository:
    def get_package(self, session_id: int) -> ReportDataPackage: ...
    def get_manifest(self, session_id: int) -> ReportManifest: ...
    def get_scope_availability(self, session_id: int) -> DataScopeAvailability: ...
    def get_session_context(self, session_id: int) -> ReportContextInput: ...
```

MVP的`get_scope_availability`可以报告兼容候选是否存在和数量，但不得读取候选报告明细进入AgentObservation。兼容候选只按相同测试类型、存在完整报告和不同session_id初筛；正式协议兼容性留给MVP-2/MVP-3。

**测试**

- 新建`tests/test_report_repository.py`，使用临时SQLite数据库；
- 覆盖实名会话、临时会话、团队会话、缺少报告详情和不存在session_id；
- 使用Spy确认构建本次Package时未调用`get_sessions`或`get_team_sessions`读取明细。

**验收标准**

- Worker只需传入`session_id`即可重建同一Package；
- 临时会话的纵向/团队可用性为False；
- 可用性元数据与授权布尔值保持独立。

**明确不做**

- 不实现历史基线选择；
- 不实现团队分层、百分位或成员级比较；
- 不开放Agent自定义数据库过滤条件。

### T1.4 持久化分析运行记录

**文件**

- 扩展`reporting/repository.py`

**存储模型**

新增`report_analyses`表：

```text
id
analysis_run_id UNIQUE
session_id
status
data_access_scope_json
package_digest
model_name
prompt_version
analysis_package_json
error_code
created_at
```

`status`限定为`running`、`validated`、`rejected`、`failed`。只有`validated`记录可以在报告固定区域作为有效分析显示。

**接口**

```python
def create_analysis_run(...) -> str: ...
def finalize_analysis_run(run_id: str, status: str, package: AnalysisPackage | None, error_code: str | None) -> None: ...
def get_latest_validated_analysis(session_id: int, scope: DataAccessScope) -> AnalysisPackage | None: ...
```

**测试**

- 临时数据库迁移、重复初始化、运行状态转换、按session/scope读取最新有效结果；
- rejected/failed结果不得作为有效分析返回；
- Package digest不匹配时旧分析不得复用。

**验收标准**

- 关闭并重新打开应用后可读取同一会话的有效分析；
- 不修改`report_detail_json`和不可变TestReport；
- 每次重跑创建新运行记录，不覆盖审计历史。

**明确不做**

- 不保存模型完整思维链；
- 不单独持久化完整Prompt；
- 不实现远程同步或多用户并发锁。

---

## 8. Phase 2：Analytical Observation Layer

### T2.1 定义并构建AgentObservation

**文件**

- 扩展`reporting/models.py`
- 新建`reporting/observation.py`

**接口**

```python
class ObservationBuilder:
    def build(
        self,
        package: ReportDataPackage,
        manifest: ReportManifest,
        availability: DataScopeAvailability,
        access_scope: DataAccessScope,
        capabilities: Sequence[AnalysisCapability],
    ) -> AgentObservation: ...
```

Phase 2只依赖`AnalysisCapability`数据契约，由测试注入固定能力描述；Phase 3完成后，`OperatorRegistry.list_capabilities(package, access_scope)`成为生产能力目录的唯一来源。这样Observation可以在Phase 2独立测试，同时不复制Operator启用状态或权限规则。

`AgentObservation`包含：

```text
report_context
report_manifest
authoritative_facts
analysis_sketch
compact_session_series
quality_summary
screening_cues
data_scope_availability
authorized_data_scopes
available_analysis_capabilities
source_refs
builder_version
```

**测试**

- 新建`tests/test_agent_observation.py`；
- 覆盖三种测试、空序列、单侧数据、排除记录和质量限制；
- 验证Observation与Manifest所有引用属于当前Package；
- 使用Fake Capability Catalog验证能力目录通过依赖注入进入Observation，Phase 2不导入`reporting.kernel`。

**验收标准**

- Observation不包含QWidget文本、UI格式化HTML、原始帧、历史明细或团队明细；
- 所有已有确定性摘要以Fact Ref表示；
- Build过程不调用模型。

**明确不做**

- 不生成最终结论、优先级或训练建议；
- 不用LLM压缩数据；
- 不查询未授权外部数据。

### T2.2 实现中性AnalysisSketch和Compact Session Series

**文件**

- 扩展`reporting/observation.py`
- 扩展`tests/test_agent_observation.py`

**接口**

```python
def build_analysis_sketch(package: ReportDataPackage) -> AnalysisSketch: ...
def build_compact_session_series(
    package: ReportDataPackage,
    max_rows: int = 80,
) -> list[CompactSessionSeries]: ...
def build_screening_cues(package: ReportDataPackage) -> list[ScreeningCue]: ...
```

**确定性表示**

- Overall：count、mean、std、min、max；
- Temporal multi-resolution：全程四等分摘要，每段记录范围和样本量；
- Side × segment：仅在侧别存在时按左/右和四等分输出；
- Cross-metric aligned view：在同一RecordSet中输出共享ordinal的主要指标列；
- Compact Session Series：`schema + rows`格式，保留ordinal、timestamp、side、inclusion、quality及主要指标；
- 当RecordSet不超过80行时保留全部行；超过80行时固定保留首尾各10行，并在剩余范围做确定性等距抽样至80行，同时记录`total_rows`、`returned_rows`和`sampling_policy`；精确记录仍可由Kernel读取完整Package。

Screening Cue第一版只允许：

```text
quality_flag_present
excluded_records_present
missing_values_present
segment_summary_available
side_summary_available
```

Cue只说明数据结构或质量线索，不输出“退化”“异常趋势”“值得重点关注”等结论。

**测试**

- 80行边界、81行抽样、首尾保留、确定性重复构建；
- 多指标行对齐和缺失占位；
- Cue内容不包含Predicate或自然语言结论；
- 删除全部Cue后，Observation仍包含Sketch和Compact Series。

**验收标准**

- 相同Package生成字节等价的规范化Observation；
- Compact Series不存在指标错位；
- Cue不能被解析为Evidence Ref。

**明确不做**

- 不做change-point、motif、疲劳检测或自适应窗口；
- 不把固定四分段结果解释为训练意义；
- 不对所有指标两两预计算相关系数。

### T2.3 Observation Token预算与序列化

**文件**

- 扩展`reporting/observation.py`

**接口**

```python
def serialize_observation(observation: AgentObservation) -> str: ...
def estimate_observation_tokens(serialized: str) -> int: ...
```

序列化使用稳定字段顺序、紧凑JSON和明确单位。Token估算只用于预算记录，不声称等同模型实际计费值。

**测试**

- 每个Fixture记录字符数、估算Token和行覆盖率；
- 超出初始`OBSERVATION_TOKEN_BUDGET`时，先减少抽样行，不删除Quality和Fact引用；
- 重复序列化同一Observation，验证输出字节一致。

**验收标准**

- 超预算时仍保留全部权威Fact、Quality摘要和截取元数据；
- 返回串能被反序列化为等价AgentObservation；
- 预算值作为配置常量和Benchmark字段，不写成已验证性能结论。

**明确不做**

- 不引入专门Arrow/Parquet存储；
- 不使用模型进行二次摘要；
- 不因Token预算删除当前报告的权威Fact索引。

---

## 9. Phase 3：OperatorRegistry、Analysis Kernel与PlanValidator

### T3.1 定义Agent计划模型和OperatorRegistry

**文件**

- 新建`agent/report/__init__.py`
- 新建`agent/report/models.py`
- 新建`reporting/kernel.py`

**计划模型**

```python
class AnalysisQuestion(BaseModel):
    question_id: str
    description: str
    dimensions: list[str]
    metric_codes: list[str]
    reason: str
    stop_condition: str

class AnalysisNode(BaseModel):
    node_id: str
    operator: str
    inputs: dict
    data_scope: Literal["current_session", "longitudinal", "cohort"]
    dependencies: list[str]
    question_id: str
    purpose: str

class SmallAnalysisPlan(BaseModel):
    questions: list[AnalysisQuestion]
    nodes: list[AnalysisNode]
```

`AnalysisQuestion`不得包含`required_scope`或`required_permission`。

**MVP Agent-level Operator**

```text
verify_temporal_change
verify_side_segment_difference
verify_cross_metric_cochange
verify_exclusion_robustness
quality_scope_check
```

Registry为纵向和团队Operator保留名称但标记`enabled=False`：

```text
longitudinal_compare
cohort_compare
```

Registry同时实现：

```python
def list_capabilities(
    package: ReportDataPackage,
    access_scope: DataAccessScope,
) -> list[AnalysisCapability]: ...
```

该方法只返回当前报告类型、数据结构、授权和Operator启用状态共同允许的语义级能力，供ObservationBuilder注入`available_analysis_capabilities`；它不得返回Kernel Primitive。

**测试**

- 新建`tests/test_operator_registry.py`；
- Operator名称唯一、输入Schema固定、支持测试类型明确；
- `list_capabilities`与Registry启用状态、测试类型和授权结果一致；
- Agent无法注册新Operator；
- MVP当前会话Operator只允许`data_scope=current_session`。

**验收标准**

- Registry是Operator权限、启用状态、输入Schema和能力目录的唯一来源；
- `AnalysisQuestion` Schema中不存在`required_scope`或同义权限字段；
- Registry及计划模型均可在无模型、无UI环境下导入和测试。

**明确不做**

- 不暴露mean、filter、groupby等Kernel Primitive给Agent；
- 不实现动态Tool注册；
- 不允许任意表达式。

### T3.2 实现权限推导和PlanValidator

**文件**

- 新建`reporting/validators.py`

**接口**

```python
class PlanValidator:
    def validate(
        self,
        plan: SmallAnalysisPlan,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
    ) -> ValidatedAnalysisPlan: ...
```

权限推导：

```text
node.operator + node.data_scope
→ OperatorRegistry
→ required scope
→ DataAccessScope检查
```

Validator同时检查：

- 最多3个Question和3个Agent-level主要节点；
- node/question引用、依赖和无环；
- metric_code和RecordSet适用性；
- side/sequence能力；
- Operator启用状态；
- 每节点目的非空；
- 规范化请求Hash不重复；
- 总成本预算。

**测试**

- 新建`tests/test_analysis_plan_validator.py`；
- 覆盖越权、禁用Operator、第四节点、循环依赖、未知指标、重复请求和伪造权限字段；
- 未授权计划被拒绝时Repository Spy证明未查询外部数据。

**验收标准**

- 只有Registry可推导`required scope`，Agent输出中不存在可覆盖该结果的字段；
- 所有非法计划在Kernel执行前被拒绝；
- 相同语义请求的规范化Hash一致，重复请求不会重复执行。

**明确不做**

- Validator不判断问题“是否值得分析”；
- Validator不替Agent生成新问题；
- 不把越权节点自动改成授权请求。

### T3.3 实现确定性Analysis Kernel

**文件**

- 扩展`reporting/kernel.py`

**接口**

```python
class AnalysisKernel:
    def execute(
        self,
        package: ReportDataPackage,
        plan: ValidatedAnalysisPlan,
    ) -> EvidenceBundle: ...
```

一个Agent-level Operator可以调用多个内部Primitive。内部计算次数不计入3节点限制，但记录在同一Tool Run的参数与Provenance中。

**MVP确定性语义**

- `increase/decrease`：比较结果差值超过MetricDefinition.numeric_tolerance；
- `comparison_supported`：参与比较的每组至少3条included有效记录，且无invalidates_metric/report质量标记；
- `persistent`：四个连续分段中至少3段方向一致，每段每组至少3条有效记录；
- `transient`：仅1～2个分段满足方向条件，且不满足persistent；
- `concentrated_on_side`：两侧前后变化均可计算，目标侧绝对变化至少为另一侧2倍且超过numeric_tolerance；
- `co_change`：两个指标来自相同RecordSet和对齐范围，均有受支持的非零方向变化；只表示共同发生，不表示相关或因果；
- `remains_after_exclusion`：包含全部有效记录与仅included记录的变化方向一致，且后者仍超过numeric_tolerance；
- `comparison_supported`作为其他比较Predicate的基础状态。

所有结果返回样本量、分段范围、值、差值、单位、Quality限制、Fact Ref、Tool Run和Provenance。

**测试**

- 新建`tests/test_analysis_kernel.py`；
- 使用固定合成记录覆盖increase、decrease、persistent、transient、concentrated_on_side、co_change、remains_after_exclusion和样本不足；
- 验证一个`verify_exclusion_robustness`节点内部可以执行筛选、分段、聚合、排除后重算并只生成一个Agent节点记录；
- 验证同一Package、版本和参数得到相同output digest。

**验收标准**

- 所有算术结果与独立测试期望值一致；
- Kernel不调用LLM；
- Kernel不读取计划范围外的RecordSet；
- `co_change`输出中明确包含`causal_interpretation_allowed=False`。

**明确不做**

- 不做统计显著性、临床意义或训练价值判定；
- 不实现相关系数、回归、因果推断、change-point和自适应窗口；
- 不实现纵向或团队计算。

---

## 10. Phase 4：Report Agent、Bounded Loop与可信输出

### T4.1 实现Report Agent和Prompt

**文件**

- 新建`agent/report/agent.py`
- 新建`agent/report/prompts/__init__.py`
- 新建`agent/report/prompts/system.md`
- 新建`agent/report/tools.py`

**接口**

```python
class ReportAgent:
    def propose_plan(
        self,
        observation: AgentObservation,
        state: AnalysisState,
    ) -> InvestigationDecision: ...

    def synthesize(
        self,
        observation: AgentObservation,
        state: AnalysisState,
        evidence: list[EvidenceBundle],
    ) -> DraftAnalysisPackage: ...
```

同一个逻辑Report Agent完成规划和综合；可以使用不同结构化Output Schema和阶段Prompt，但不拆成多个角色Agent。

Prompt必须声明：

- 正式数值只能引用Fact/Evidence占位符；
- Cue不是Evidence；
- 未授权数据域只能建议扩展；
- 最多3个问题和3个主要节点；
- 禁止诊断、因果和无来源阈值；
- `co_change`只表示共同变化。

**测试**

- 新建`tests/test_report_agent_contract.py`，使用Fake PydanticAI输出；
- 验证AnalysisQuestion无权限字段、Node只声明data_scope；
- 验证Prompt包含权限、证据和禁止声明约束；
- 导入`agent.report.models`不发起网络请求。

**验收标准**

- Agent输出只能通过Pydantic结构化模型进入Loop；
- Agent没有数据库连接和自由代码Tool；
- 真实模型接入前所有流程可用Fake Agent执行。

**明确不做**

- 不支持自由聊天、追问和长期Memory；
- 不实现RAG、知识库、Multi-Agent或多模型路由；
- 不流式展示未校验的分析文本。

### T4.2 实现两周期Analysis Loop

**文件**

- 新建`agent/report/analysis_loop.py`

**接口与限制**

```python
MAX_INVESTIGATION_CYCLES = 2
MAX_REPLANS = 1
MAX_ANALYSIS_QUESTIONS_PER_CYCLE = 3
MAX_AGENT_LEVEL_NODES_PER_CYCLE = 3

class AnalysisLoop:
    def run(
        self,
        observation: AgentObservation,
        access_scope: DataAccessScope,
    ) -> LoopResult: ...
```

流程：

```text
propose_plan
→ validate
→ batch execute
→ update hypotheses
→ sufficient则结束
→ conflict/unresolved则Replan一次
→ second batch
→ synthesize
```

`AnalysisState`保留Question、active/supported/rejected Hypothesis、Evidence Ref、未解决问题、cycle_count和replan_count。Replan不清空历史。

**测试**

- 新建`tests/test_report_analysis_loop.py`；
- Fake Agent分别覆盖一轮完成、第一轮假设被否定后Replan、第二轮仍不充分、重复计划和越权计划；
- 断言最多调用两次Planner/执行器，不存在第三周期；
- Replan保留第一轮Evidence和rejected Hypothesis。

**验收标准**

- 充分Evidence不触发第二轮；
- 仅证据冲突、质量限制或未解决问题可触发Replan；
- 达到预算时输出限制说明，不继续Tool Loop。

**明确不做**

- 不实现通用Graph、树搜索或任意次数循环；
- 不让LLM单独决定是否突破预算；
- 不并发执行具有依赖关系的节点。

### T4.3 定义AnalysisPackage和MVP Predicate

**文件**

- 扩展`agent/report/models.py`
- 扩展`reporting/models.py`

**核心类型**

```text
AnalysisClaim
NumericBinding
PredicateBinding
ScopeExpansionSuggestion
AnalysisPackage
```

MVP Predicate白名单：

```text
increase
decrease
persistent
transient
concentrated_on_side
co_change
remains_after_exclusion
comparison_supported
```

描述性Claim可以只绑定`fact_refs`；派生Claim必须绑定`evidence_refs`和`tool_run_ids`；综合Claim必须绑定所有主要证据。

**测试**

- 白名单外Predicate在Pydantic或Validator阶段拒绝；
- Agent不能直接提供最终数值，只能提供NumericBinding占位符；
- 未授权范围建议使用`ScopeExpansionSuggestion`，不得伪装为Claim。

**验收标准**

- 描述性Claim、派生Claim和范围扩展建议三者Schema可判别且不能互相伪装；
- Predicate集合严格等于MVP白名单；
- Draft Schema中不存在可让Agent直接写入最终展示数值的字段。

**明确不做**

- 不构建通用自然语言逻辑引擎；
- 不允许Agent创建新Predicate；
- 不加入“显著”“危险”“受伤风险”等未定义Predicate。

### T4.4 实现Claim Validator和Renderer

**文件**

- 扩展`reporting/validators.py`
- 新建`reporting/renderer.py`

**接口**

```python
class ClaimValidator:
    def validate(
        self,
        draft: DraftAnalysisPackage,
        package: ReportDataPackage,
        evidence: list[EvidenceBundle],
        access_scope: DataAccessScope,
    ) -> ValidatedAnalysisPackage: ...

class AnalysisRenderer:
    def render(self, package: ValidatedAnalysisPackage) -> AnalysisPackage: ...
```

Validator检查Fact、Evidence、Tool Run、快照、单位、Predicate来源、授权、样本量、Quality限制、因果词、医学诊断和无来源数字。Renderer根据Fact/Evidence注入数值与单位。

**测试**

- 新建`tests/test_analysis_claim_validator.py`和`tests/test_analysis_renderer.py`；
- 覆盖直接Fact、派生证据、未知Fact、其他快照Fact、白名单外Predicate、无Tool Run、越权、Quality禁止、因果和医学诊断；
- 验证同一Validated Package渲染结果确定一致。

**验收标准**

- Fixture Numeric Accuracy与Evidence Resolution Rate均为100%；
- Unsupported Claim Rate为0；
- 未通过的Claim不进入最终UI文本；
- Renderer不调用LLM。

**明确不做**

- 不自动修复越权或无证据Claim；
- 不使用LLM二次校验；
- 不生成训练处方或医学建议。

### T4.5 实现ReportAnalysisService

**文件**

- 新建`agent/report/service.py`

**接口**

```python
class ReportAnalysisService:
    def analyze(
        self,
        session_id: int,
        access_scope: DataAccessScope,
    ) -> AnalysisPackage: ...
```

Service负责：创建运行记录、获取Package和Availability、构建Observation、运行Loop、校验、渲染、持久化状态。任何异常转换为稳定`error_code`，不得返回半成品文本。

**测试**

- 新建`tests/test_report_analysis_service.py`；
- 使用Fake Agent和临时Repository覆盖成功、Builder失败、模型失败、Validator拒绝和持久化失败；
- 验证只有validated结果可读取和显示。

**验收标准**

- 输入只有`session_id + DataAccessScope`；
- Service不接受UI表格文本或完整报告JSON；
- 重跑不修改已有分析运行记录。

**明确不做**

- 不实现异步任务队列、取消恢复和跨进程续跑；
- 不实现纵向或团队分析；
- 不允许用户编辑并回写Agent结果。

---

## 11. Phase 5：单Worker报告协议与持久化联调

### T5.1 增加报告分析路由

**文件**

- 修改`agent/worker.py`
- 修改`ui/llm_client.py`，将类名调整为`AgentWorkerClient`

**接口**

```text
POST /report/analyze
```

请求：

```json
{
  "session_id": 123,
  "data_access_scope": {
    "current_session": true,
    "longitudinal": false,
    "cohort": false
  }
}
```

成功响应：

```json
{
  "analysis": {},
  "analysis_run_id": "run_..."
}
```

失败响应包含稳定`error_code`，不返回Traceback给UI；完整异常只写本地日志。

`AgentWorkerClient.analyze_report(session_id, scope, timeout=120) -> dict`调用该路由。配置与报告分别使用`_config_lock`和`_report_lock`。

**测试**

- 扩展`tests/test_agent_worker_routes.py`和`tests/test_llm_client.py`；
- 覆盖请求Schema、非法scope、会话不存在、Service错误、超时及配置/报告锁隔离；
- 验证旧配置接口仍通过。

**验收标准**

- Worker中ConfigService与ReportAnalysisService为不同单例；
- 报告分析不会重置Config对话历史；
- HTTP层不接收任意Tool参数、SQL或完整报告JSON。

**明确不做**

- 不提供Agent逐Tool HTTP端点；
- 不向UI流式发送未验证Claim；
- 不增加第二Worker。

### T5.2 记录运行预算与审计信息

**文件**

- 扩展`agent/report/service.py`
- 扩展`reporting/models.py`
- 扩展`reporting/repository.py`
- 扩展`tests/test_report_analysis_service.py`

**接口**

```python
class AnalysisRunMetrics(BaseModel):
    model_name: str
    prompt_version: str
    observation_builder_version: str
    operator_registry_version: str
    package_digest: str
    cycle_count: int
    replan_count: int
    agent_level_node_count: int
    tool_run_count: int
    duplicate_request_count: int
    observation_size: int
    estimated_tokens: int
    elapsed_ms: int
```

每次分析记录：

```text
model_name
prompt_version
observation_builder_version
operator_registry_version
package_digest
cycle_count
replan_count
agent_level_node_count
tool_run_count
duplicate_request_count
observation_size
estimated_tokens
elapsed_ms
```

这些字段写入AnalysisPackage元数据或分析运行记录，用于Benchmark，不写成性能提升结论。

**测试**

- 成功、Validator拒绝和模型异常三条路径均写入Metrics；
- 验证持久化JSON中不含Prompt正文、思维链或外部明细。

**验收标准**

- 所有validated/failed/rejected运行均有状态和耗时；
- 不保存模型隐藏思维链；
- 不记录未授权外部数据内容。

**明确不做**

- 不实现高级Token Scheduler；
- 不建立远程遥测服务；
- 不上传运动员数据。

---

## 12. Phase 6：报告UI集成

### T6.1 让报告页获得session_id

**文件**

- 修改`ui/views/history_view.py`
- 修改`ui/main_window.py`
- 修改`ui/views/report_view.py`

**接口调整**

```python
ReportView.load_report(report: TestReport, session_id: int | None = None) -> None
```

`HistoryView.open_report_requested`改为发送`SessionRecord`，MainWindow再调用：

```python
report_view.load_report(session.report, session.id)
```

即时测试在`record_session`成功后使用`_last_session_id`加载报告。持久化失败或没有SubjectStore时传入`None`。

**测试**

- 更新`tests/test_history_view.py`、`tests/test_main_window_navigation.py`和报告视图测试；
- 验证即时、历史、临时和无持久化会话的session_id传递。

**验收标准**

- Worker不接收内存TestReport；
- UI显示的报告和Worker分析的session_id对应同一保存快照；
- `session_id=None`时智能分析不可用但基础报告正常。

**明确不做**

- 不改变报告基础卡片、图表和表格的数据来源；
- 不把session_id写进不可变TestReport；
- 不让HistoryView直接调用Agent。

### T6.2 增加唯一智能分析入口和固定结果区域

**文件**

- 修改`ui/views/report_view.py`

**接口**

```python
ReportView.set_analysis_context(session_id: int | None) -> None
ReportView.set_analysis_loading(loading: bool) -> None
ReportView.show_validated_analysis(analysis: AnalysisPackage) -> None
ReportView.clear_analysis() -> None
```

新增：

- 一个明显的“智能分析”按钮；
- 分析中状态；
- 固定智能分析结果容器；
- 重新分析操作；
- Evidence/限制信息的只读展示区域。

MVP只分析本次记录，不显示尚未实现的纵向和团队复选框。MVP-2/MVP-3实现后仍在同一入口内增加范围选择，不增加新的分析按钮或模式。

**测试**

- 新建`tests/test_report_analysis_ui.py`；
- 覆盖入口显隐、点击一次、重复点击防抖、加载已有validated结果、失败不显示半成品、切换报告清空旧状态；
- 验证基础报告布局和现有详情页回归。

**验收标准**

- 加载报告不会自动调用模型；
- 只有用户点击后调用`analyze_report`；
- 结果校验成功后直接进入固定区域，不要求二次确认；
- rejected/failed结果只显示稳定错误提示，不显示Agent草稿。

**明确不做**

- 不增加“深度分析”“纵向分析”“横向分析”等独立模式按钮；
- 不提供可编辑Agent正文；
- 不在UI中重新计算分析指标。

### T6.3 Worker可用性与离线行为

**文件**

- 修改`ui/main_window.py`
- 修改`ui/views/report_view.py`
- 扩展`AgentWorkerClient`

**接口**

```python
AgentWorkerClient.get_status() -> Literal[
    "ready", "starting", "warming", "stopped", "unreachable", "error"
]
ReportView.set_analysis_availability(available: bool) -> None
```

进入报告页时，MainWindow检查Worker状态；必要时后台启动Worker。状态为`ready`时显示入口；`starting/warming`时保持入口隐藏并等待健康更新；`stopped/unreachable/error`时隐藏入口和结果区域。Worker异常退出后立即隐藏入口，但不影响基础报告。

**测试**

- Fake Client覆盖ready、warming、stopped、unreachable和error；
- 离线状态不创建分析HTTP请求；
- Worker恢复ready后可显示入口；
- 应用关闭时仍只有一个Worker停止流程。

**验收标准**

- 只有`ready + session_id存在 + 报告类型受支持`时入口可见；
- Worker状态变化不影响基础报告浏览；
- 离线或Worker异常时结果区与入口同步隐藏。

**明确不做**

- 不通过外部网站探测网络；
- 不提供离线规则版智能报告；
- 不在离线时显示旧的未验证草稿。

### T6.4 展示持久化结果

**文件**

- 扩展`ui/llm_client.py`
- 扩展`ui/views/report_view.py`
- 扩展`tests/test_report_analysis_ui.py`

**接口**

```python
AgentWorkerClient.get_latest_analysis(
    session_id: int,
    scope: DataAccessScope,
) -> dict | None
```

报告加载后可以通过Client或本地Repository读取与当前Package digest、scope匹配的最新validated结果。若存在则显示固定区域；不存在则保持区域隐藏，直到用户点击并成功分析。

**测试**

- 重启模拟后能显示已保存结果；
- 报告详情变化导致digest改变时不复用旧结果；
- 重跑后显示最新validated结果，同时旧运行仍可审计。

**验收标准**

- UI只展示`validated + digest匹配 + scope匹配`的结果；
- Worker返回空结果时不留下上一会话内容；
- 读取已有结果不调用模型、不增加Token计数。

**明确不做**

- 不提供历史分析版本选择UI；
- 不自动重跑过期分析；
- 不在报告导出中加入AI结果，导出支持留到后续任务。

---

## 13. Phase 7：端到端验收与Benchmark

### T7.1 建立固定合成模式集

**文件**

- 新建`tests/reporting_fixtures.py`
- 新建`tests/test_report_agent_end_to_end.py`
- 新建`tools/benchmark_report_agent.py`

**接口**

```python
def load_report_agent_cases() -> list[BenchmarkCase]: ...
def run_report_agent_benchmark(
    cases: Sequence[BenchmarkCase],
    repetitions: int,
) -> BenchmarkResult: ...
```

至少覆盖：

1. 单一后程增加；
2. 左右差异；
3. 左侧差异只在后程出现；
4. 触地时间增加且步长下降；
5. 右侧稳定、左侧变化；
6. 单个异常值制造假趋势；
7. 排除异常值后趋势仍存在；
8. 排除后方向反转；
9. 相同均值但离散程度不同；
10. 样本量不足；
11. 质量标记限制声明；
12. 初始假设被Evidence否定后Replan。

**测试**

- `tests/test_report_agent_end_to_end.py`以Fake Agent逐个运行12类Fixture；
- Benchmark以固定模型、Prompt和重复次数运行同一Case集合；
- 结果文件校验每个Case均包含期望Predicate、允许的Claim集合和必须拒绝的Claim集合。

**确定性验收**

- Builder字段、数值、顺序、状态和引用全部匹配Fixture；
- Kernel Numeric Accuracy = 100%；
- Evidence Resolution Rate = 100%；
- Unsupported Claim Rate = 0%；
- 越权数据访问率 = 0%；
- 相同输入、Operator版本和参数的digest一致。

**真实模型MVP门槛**

- 固定12类模式，每类至少3次独立运行；
- Hidden Pattern Recall ≥ 0.80；
- Hidden Pattern Precision ≥ 0.80；
- Cross-dimension Discovery Rate ≥ 0.80；
- Numeric Accuracy、Evidence Resolution Rate保持100%；
- Unsupported Claim Rate和权限违规率保持0%；
- P95总延迟不超过当前客户端120秒超时；
- Token、P50/P95延迟和重复调用率记录为工程基线，不表述为研究结论。

上述门槛只用于MVP工程放行。论文中的准确率、有效性和改进幅度必须经过独立标注与正式实验后另行报告。

**明确不做**

- 不把工程门槛解释为临床、训练或真实运动表现有效性；
- 不以真实运动员隐私数据作为默认Benchmark Fixture；
- 不因模型表现不足而放宽Numeric、Evidence或权限的100%硬约束。

### T7.2 消融测试

**文件**

- 扩展`tools/benchmark_report_agent.py`
- 扩展`tests/test_report_agent_end_to_end.py`

**接口**

```python
class AblationConfig(BaseModel):
    include_sketch: bool
    include_compact_series: bool
    include_screening_cues: bool
    max_replans: Literal[0, 1]
```

```text
A：仅Summary
B：AnalysisSketch + Compact Series
C：B + Screening Cues
D：C + 最多一次Replan
```

比较Hidden Pattern Recall、Precision、Tool选择、Token和延迟。Screening Cue仅在C/D出现，Claim Validator规则保持一致。

**测试**

- 对同一Case、模型和重复次数执行A～D四组配置；
- 验证各组只改变AblationConfig声明的输入或循环开关；
- 验证四组均使用同一Kernel、Predicate白名单和Claim Validator。

**验收标准**

- 能独立关闭Cue和Replan；
- 无Cue时Agent仍能从Observation提出问题；
- 消融结果如实记录，不预设Cue或Replan必然提高指标。

**明确不做**

- 不开展用户实验、运动员招募或医学有效性研究；
- 不把合成模式结果称为真实运动分析准确率；
- 不加入纵向、团队或知识RAG对照组。

### T7.3 全量回归

**文件**

- 运行仓库现有`tests/`及本计划新增测试；除修复本计划引入的回归外，不修改生产文件
- Benchmark输出写入临时或明确指定的结果目录，不提交包含密钥或受试者明细的文件

**接口**

本任务不新增运行时接口；验收入口为测试命令和`tools/benchmark_report_agent.py`命令行参数。

执行：

```text
QT_QPA_PLATFORM=offscreen conda run -n Iron_Jump python -m pytest -q
```

并单独运行：

```text
Config Agent回归
Worker路由测试
Reporting纯确定性测试
Report Agent Fake模型测试
Report UI测试
真实模型Benchmark（非CI）
```

**验收标准**

- 原有测试无新增失败；
- 新增确定性和Fake模型测试全部通过；
- 真实模型Benchmark生成包含模型、Prompt、Package和Operator版本的结果文件；
- 不因Report Agent引入硬件、Engine或采集线程修改。

**明确不做**

- 不在CI中调用付费真实模型；
- 不借全量回归重构无关测试或生产模块；
- 不在测试失败时降低既定Evidence、权限和数值验收标准。

---

## 14. MVP明确不做

- 个人历史纵向计算和基线选择；
- 团队横向比较、分层和百分位；
- 用户自定义数据筛选或SQL；
- 高级change-point、adaptive window、motif和疲劳算法；
- RAG、Vector Database和领域知识建议；
- Multi-Agent、Multi-Model和Pydantic Graph；
- 任意次数Replan、长期Memory和自动反思；
- 训练处方、伤病预测、医学诊断和因果结论；
- AI结果编辑、二次确认、导出和远程同步；
- 原始1000Hz数据、完整足迹回放、历史报告或团队成员明细进入LLM上下文；
- 为实现Report Agent修改红外光电传感器采集、GaitEngine计算或现有TestReport正式数值。

---

## 15. 架构文档逐条回查

| 回查项 | 本计划覆盖位置 | 结果 |
|---|---|---|
| 确定性算法负责正式数值，Agent不自由计算 | AR-10、Phase 3、T4.4 | 已覆盖 |
| Config Agent与Report Agent业务解耦 | Phase 0目标目录与T0.1～T0.3 | 已覆盖 |
| 单Worker、不同路由和状态隔离 | T0.3、T5.1 | 已覆盖 |
| TestReport不可变并通过Builder转换 | T1.2 | 已覆盖 |
| RecordSet优先、Series为投影 | AR-04、T1.1～T1.2 | 已覆盖 |
| 三类测试使用区分Payload | T1.1～T1.2 | 已覆盖；旧GaitTestReport明确排除 |
| Missing、Exclusion、Quality显式表示 | T1.1～T1.2 | 已覆盖 |
| 稳定ID、Provenance、Tool Run和digest | T1.1～T1.4、T3.3 | 已覆盖 |
| UI与Agent共用reporting数据层但互不依赖 | 目标依赖方向、T6.1 | 已覆盖 |
| ReportManifest降级为导航元数据 | T1.1～T1.3、T2.1 | 已覆盖；保留轻量Manifest及稳定引用，但不作为唯一首轮输入或洞察入口 |
| 原架构“Manifest作为首次唯一入口”的表述 | 文档优先级说明、AR-08、Phase 2 | 已被修订版替代，不按旧流程实施 |
| Analytical Observation Layer成为首轮入口 | Phase 2 | 已覆盖 |
| AnalysisSketch与Compact Series同时存在 | T2.1～T2.2 | 已覆盖 |
| Screening Cue只作辅助且不能成为Evidence | AR-09、T2.2、T4.4 | 已覆盖 |
| 原架构“Screening Profile主导选题”的表述 | AR-09、T2.2、T7.2 | 已被修订版替代；保留Cue消融验证 |
| DataScopeAvailability与DataAccessScope分离 | T1.1、T1.3、T2.1 | 已覆盖 |
| 产品只有一个“智能分析” | T6.2 | 已覆盖 |
| 用户点击后才调用模型，离线隐藏 | T6.2～T6.3 | 已覆盖 |
| Agent不填写required_scope | T3.1 | 已覆盖 |
| 节点声明data_scope，权限由Registry推导 | T3.1～T3.2 | 已覆盖 |
| 直接Fact无需重复Tool计算 | T1.2、T4.3～T4.4 | 已覆盖 |
| 派生趋势、比较和关系必须经Kernel验证 | T3.3、T4.4 | 已覆盖 |
| Agent-level Operator与Kernel Primitive分离 | T3.1、T3.3 | 已覆盖 |
| 3节点限制不约束Kernel内部子计算 | T3.3 | 已覆盖 |
| MVP小计划批量执行、最多一次Replan | T4.2 | 已覆盖 |
| 长期保留Bounded Hypothesis Loop | T4.2说明及MVP不做项 | 已覆盖，不实现超过两周期 |
| Replan保留既有Evidence与Rejected Hypothesis | T4.2 | 已覆盖 |
| 跨维度综合进入MVP | T3.3、T4.3、T7.1 | 已覆盖 |
| MVP Predicate使用小白名单 | T4.3～T4.4 | 已覆盖 |
| Numeric Binding与确定性Renderer | T4.3～T4.4 | 已覆盖 |
| Claim Validator限制权限、质量、因果和诊断 | T4.4 | 已覆盖 |
| 横向/纵向从架构预留但按阶段实现 | T1.1、T3.1；MVP不做项 | 已覆盖；本MVP不执行外部比较 |
| 外部比较在数据库侧计算且不把明细交给LLM | T1.3、T3.2；MVP不做项 | 接口和拒绝路径已覆盖，计算留MVP-2/3 |
| CompatibilityResult与正式历史/团队兼容性协议 | T1.3的候选可用性与MVP不做项 | 有意延后到MVP-2/3；本MVP没有外部比较结果，不能伪造兼容性结论 |
| 分层读取、按需精确验证和Exact Row可恢复 | T1.1～T1.3、T2.2、T3.3 | 已覆盖；LLM看紧凑Observation，Kernel从完整Package确定性取精确行 |
| Tool、Agent Logic和Validator职责分离 | Phase 3、T4.1～T4.4 | 已覆盖；不额外创建单用途“Skill”运行层 |
| Token、Tool次数、循环和重复请求受控 | T2.3、T3.2、T4.2、T5.2 | 已覆盖 |
| AnalysisPackage可追溯、保存和重开 | T1.4、T4.5、T6.4 | 已覆盖 |
| Graph、RAG、Vector DB、Multi-Agent等延后 | MVP明确不做 | 已覆盖 |
| 定量验证和消融测试 | Phase 7 | 已覆盖 |

回查结果：修订版架构要求均已映射到实施任务或明确的MVP排除项。唯一有意延后的能力是个人历史纵向计算和团队横向计算；本MVP只实现数据范围Schema、权限推导、禁用Operator和无越权查询验收，为MVP-2和MVP-3保留兼容接口。
