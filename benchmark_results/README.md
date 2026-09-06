# Report Agent 联网 MVP Benchmark

运行日期：2026-08-08  
模型：`deepseek-v4-flash`  
最终 Prompt：`report-agent-system/1.1`  
每组：12 类固定合成案例 × 3 次独立运行

观察输入决策（2026-08-10）：采用 B 作为默认配置，即开启 AnalysisSketch 与 Compact Series，关闭 Screening Cues。2026-08-11 生产执行器已经迁移为单步序贯分析循环，以下 A～D 结果保留为输入结构消融依据。

## 最终消融结果

| 组别 | 观察输入 | Replan | 有效运行 | Expected Predicate Recall | P50 | P95 |
|---|---|---:|---:|---:|---:|---:|
| A | 权威 Fact、Manifest、Quality、Capability | 禁用 | 34/36 | 0.424 | 20.2 s | 35.8 s |
| B | A + AnalysisSketch + Compact Series | 禁用 | 35/36 | 0.879 | 19.6 s | 35.1 s |
| C | B + Screening Cues | 禁用 | 35/36 | 0.818 | 19.4 s | 38.6 s |
| D | C + 最多一次 Replan | 启用 | 34/36 | 0.879 | 19.7 s | 33.1 s |

## 可支持的工程结论

- B 相比 A 的 Recall 明显提高，支持向 Agent 提供 AnalysisSketch 和 Compact Series，而不是只提供摘要与索引。
- C 未优于 B，本批合成结果不支持“Screening Cues 必然提高发现率”。Cue 应继续保持辅助线索地位。
- 所有有效运行均在一个调查周期内结束，Replan 实际触发数为零。因此本批数据不能评价 Replan 的收益。
- 所有组的 P95 均低于客户端 120 秒超时。
- Validator 没有放行错误数值、无证据派生声明、越权数据访问或因果/医学声明。

## 重要限制

- 当前 Case 只标注了必须发现的 `expected_predicates`，没有标注所有允许出现的辅助谓词。`comparison_supported`、方向谓词等合法证据不能直接算作误报，因此旧 JSON 中的 `hidden_pattern_precision` 不是有效的 Hidden Pattern Precision。
- A、B、C 三组并行运行，D 组串行运行；绝对延迟只能用于超时检查，不能据此推断不同输入结构造成的延迟差异。
- 这是合成数据工程验收，不代表真实运动员分析准确率、训练有效性或医学有效性。
- 少数失败来自模型结构化输出重试耗尽或 NumericBinding 占位符仍不一致；这些输出均被 Validator 拒绝，没有展示为有效报告。
- 当前案例没有为所有合法辅助 Predicate 建立 allowed-set，因此不计算正式 Hidden Pattern Precision，也不将旧 JSON 中的该字段用于方案排名。

## 当前回归状态

2026-08-12 使用 `QT_QPA_PLATFORM=offscreen` 运行全量测试：`659 passed`、`12 subtests passed`。

## 单步序贯循环发布验收

2026-08-11 使用 B 观察配置和生产单步序贯循环执行 12 类固定合成案例 × 3 次。结果为 36/36 有效运行（100%）、Expected Predicate Recall 25/27（92.59%）、决策断言通过率 96.53%、P50 17.875 s、P95 47.931 s。该结果保存于 `report_agent_sequential_b_12x3_20260811.json`。

上述结果满足预先设定的有效运行率不低于 90%、Expected Predicate Recall 不低于 0.80、P95 低于 120 s 三项工程门槛。它仍然只属于固定合成案例，不能解释为真实运动员分析准确率。

## 三工具边界迁移复测

2026-08-10 使用 `report-agent-system/2.0` 和生产默认 B 重新执行 12 类合成案例 × 3 次。结果为 34/36 有效运行（94.44%）、Expected Predicate Recall 0.879、P50 19.716 s、P95 29.004 s；全部有效运行的 `replan_count` 为 0。两次失败均来自 `replan_required` 案例，一次被 NumericBinding 占位符校验拒绝，一次在结构化输出重试后失败。该复测只验证 Tool/Method 边界迁移后的工程回归，不改变前述真实数据证据限制。

## 原始结果

- `report_agent_A_3x.json`
- `report_agent_B_3x.json`
- `report_agent_C_3x.json`
- `report_agent_D_final_3x.json`
- `report_agent_three_tool_b_20260810.json`

其他 JSON 是 smoke、契约修正和连接错误复测记录，保留用于审计，不应与最终四组结果合并计算。
