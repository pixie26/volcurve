# VolCurve 文档导航

当前修订：2026-08-09

本文是 `docs/` 的**唯一导航入口**。项目经历了 Phase A–F、Stabilization Step 1–7，以及 Frontend 7.5 correctness/modularization。多份早期 acceptance 文档仍有审计价值，但其中的 UI、测试数量、repo visibility 或后续计划可能已经过时。阅读时应先区分“当前契约”与“历史证据”。

## 当前应优先阅读的文档

| 文档 | 角色 | 是否持续更新 |
|---|---|---|
| [`../README.md`](../README.md) | 项目入口、运行方法、当前能力概览 | 是 |
| [`optimization_review_zh.md`](optimization_review_zh.md) | 当前实现状态、关键设计决策、技术债与 roadmap | 是 |
| [`phase_f_compare_indicator_builder_zh.md`](phase_f_compare_indicator_builder_zh.md) | Time Series 当前产品/交互契约 | 是 |
| [`frontend_testing_zh.md`](frontend_testing_zh.md) | Time Series 前端代码边界、pure-core ownership、Node/Playwright/CI 测试职责 | 是 |
| [`operations_runbook_zh.md`](operations_runbook_zh.md) | 部署、并发、故障、持久卷、备份恢复与 release gate | 是 |
| [`data_retention_policy_zh.md`](data_retention_policy_zh.md) | licensed market data 的保存、清理、备份与合同责任边界 | 是 |
| [`validation_report.md`](validation_report.md) | 2026-08-07 Phase E live validation 的历史快照及当前适用边界 | 历史快照，必要时加勘误 |

## 当前代码/验证基线

Frontend 7.5 A–G 已关闭：

```text
compare-core.js
  canonical pure statistics / derived / signatures
        ↓
compare-workspace.js
  workspace / boards / bulk / persistence
        ↓
compare-request.js
  request serialization / fetch / series resolution
        ↓
compare-render.js
  DOM / Plotly / details / statistics table
        ↓
compare-builder.js
  thin bootstrap / orchestration
```

用户可见 Time Series range statistics 与 browser-derived series 以 `compare-core.js` 为 canonical implementation；Node tests 直接执行 production core。后端 `app/analytics/statistics.py` 因仍服务 `AnalyticsEngine.run_compare` / `CompareSummary` contract 而保留。

前端行为验证职责固定为：

- **Node**：数值、derived arithmetic、signatures、architecture boundaries；
- **Playwright Chromium**：页面 boot、真实 interaction、request serialization、runtime errors；
- **Python Web tests**：静态 product/asset/security/disclosure contracts；
- **GitHub Actions**：把 Python + Node + Chromium + security/diff checks 串成 merge/push gate。

详细边界见 [`frontend_testing_zh.md`](frontend_testing_zh.md)。

## 历史 acceptance 文档

以下文档保留是为了回答“当时什么 Gate 通过、证据是什么”，**不再作为当前产品说明或 roadmap**：

- [`phase_a_acceptance_zh.md`](phase_a_acceptance_zh.md)
- [`phase_b_acceptance_zh.md`](phase_b_acceptance_zh.md)
- [`phase_c_acceptance_zh.md`](phase_c_acceptance_zh.md)
- [`phase_d_acceptance_zh.md`](phase_d_acceptance_zh.md)

它们中的固定测试数量、旧 UI 流程（例如 5-chart、Load/Apply、手输 Listed expiry）、旧 Phase 计划等均可能已被后续实现覆盖。出现冲突时，优先级为：

```text
代码与自动执行测试
  > 当前 living docs
  > 最新 OpenAPI / live probe evidence
  > 历史 acceptance docs
```

其中 BNP wire contract 的字段与模式判断应以 repo 内当前 OpenAPI、serializer/request model 以及可重复 live probe 为共同依据，不能单独依赖旧文字描述。

## 当前文档边界

为减少重复，后续按以下原则维护：

- **README**：项目概览、启动、核心语义、当前状态与入口链接；
- **optimization review**：唯一 living status / technical debt / roadmap；
- **Time Series contract**：当前用户可见产品语义；
- **frontend testing**：前端代码 ownership、测试分层与 refactor guardrails；
- **operations runbook**：部署、故障处理、持久卷、审计与恢复操作；
- **data retention policy**：licensed data 生命周期与责任边界；
- **validation report / phase acceptance**：带日期的历史证据快照，不把旧测试数字滚动更新成“当前数字”。

不要再新增另一份“当前状态总表”。如果实现、测试和 roadmap 发生变化，优先修改上述 living docs，而不是继续堆新的 Phase 文档。

## 当前最重要的未完成项

### P0 — Step 8 Historical Archive Operations

Step 7 之后 `history.duckdb` 已成为需要独立保护的长期数据资产，因为安全覆盖后的旧 request raw 可以被 compact。下一阶段必须补齐：

1. **Audit / inspection**：schema、coordinate、coverage、point、revision 基本一致性检查；输出 counts/hash/date ranges，不泄露行情值。
2. **Migration / maintenance**：从现有 completed exact K/F/K/S/Delta request cache 幂等 backfill；dry-run、non-destructive default、成功后再允许 compaction。
3. **Backup / restore verification**：DuckDB-safe snapshot、临时恢复、history audit、raw hash audit、fixture smoke，以及 interrupted/corrupt/partial restore 演练。

只有 Step 8 完成，Step 7 historical archive 才算具备生产级长期运行条件。

### P1 — Persistent HTTP client lifecycle

当前真实 Cortex attempt 仍为每次请求创建/关闭 `httpx.Client`。后续在不改变 single-flight、4-slot limiter、auth/retry、fixture/cache/archive semantics 的前提下引入受控连接池与 shutdown lifecycle。

### P1 — Deployment release gate

实际 Docker 主机复验、persistent-volume restore drill、repository private、反向代理/ACL；若服务从小型可信团队扩大，再重新评估 Cortex Playground 的独立 enable flag / route auth。

任何新改动如果改变上述优先级，应先更新 [`optimization_review_zh.md`](optimization_review_zh.md)。