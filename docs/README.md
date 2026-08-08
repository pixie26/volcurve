# VolCurve 文档导航

当前修订：2026-08-08

本文是 `docs/` 的**唯一导航入口**。项目经历了 Phase A–F 和 Stabilization Step 1–7，多份早期 acceptance 文档仍有审计价值，但其中的 UI、测试数量、repo visibility 或后续计划可能已经过时。阅读时应先区分“当前契约”与“历史证据”。

## 当前应优先阅读的文档

| 文档 | 角色 | 是否持续更新 |
|---|---|---|
| [`../README.md`](../README.md) | 项目入口、运行方法、当前能力概览 | 是 |
| [`optimization_review_zh.md`](optimization_review_zh.md) | 当前实现状态、关键设计决策、未完成事项与 roadmap | 是 |
| [`phase_f_compare_indicator_builder_zh.md`](phase_f_compare_indicator_builder_zh.md) | Time Series 当前产品/交互契约 | 是 |
| [`operations_runbook_zh.md`](operations_runbook_zh.md) | 部署、并发、故障、持久卷、备份恢复与 release gate | 是 |
| [`data_retention_policy_zh.md`](data_retention_policy_zh.md) | licensed market data 的保存、清理、备份与合同责任边界 | 是 |
| [`validation_report.md`](validation_report.md) | 2026-08-07 Phase E live validation 的历史快照及当前适用边界 | 历史快照，必要时加勘误 |

## 历史 acceptance 文档

以下文档保留是为了回答“当时什么 Gate 通过、证据是什么”，**不再作为当前产品说明或 roadmap**：

- [`phase_a_acceptance_zh.md`](phase_a_acceptance_zh.md)
- [`phase_b_acceptance_zh.md`](phase_b_acceptance_zh.md)
- [`phase_c_acceptance_zh.md`](phase_c_acceptance_zh.md)
- [`phase_d_acceptance_zh.md`](phase_d_acceptance_zh.md)

它们中的固定测试数量、旧 UI 流程（例如 5-chart、Load/Apply、手输 Listed expiry）、旧 Phase 计划等均可能已被后续实现覆盖。出现冲突时，优先级为：

```text
代码与自动测试
  > 当前 living docs
  > 最新 OpenAPI / live probe evidence
  > 历史 acceptance docs
```

其中 BNP wire contract 的字段与模式判断应以 repo 内当前 OpenAPI、serializer/request model 以及可重复 live probe 为共同依据，不能单独依赖旧文字描述。

## 当前文档边界

为减少重复，后续按以下原则维护：

- **README** 只保留项目概览、启动、核心语义和链接，不复制完整设计史；
- **optimization review** 作为 living status/roadmap，不再重复逐 Phase 的完整历史验收过程；
- **Time Series contract** 只描述当前用户可见产品语义，以及直接影响 UI 的 cache/stale 行为；
- **operations runbook** 只描述部署和运行时操作；
- **data retention policy** 只描述 licensed data 生命周期与责任边界；
- **validation report / phase acceptance** 保留为带日期的证据快照，不把历史测试数字更新成“当前数字”。

## 当前最重要的未完成项

1. **Historical archive operational hardening**：为 `history.duckdb` 增加可重跑迁移/审计、coverage/revision inspection 和经过验证的备份恢复路径。Step 7 之后部分旧 request raw 可以被 compact，因此历史点库本身已成为需要独立保护的长期数据资产。
2. **Persistent HTTP client lifecycle**：当前真实 Cortex attempt 仍为每次请求创建/关闭 `httpx.Client`；后续在不改变 single-flight、4-slot limiter、auth/retry 语义的前提下引入受控连接池与 shutdown lifecycle。
3. **Deployment release gate**：实际 Docker 主机复验、repository private、反向代理/ACL；若服务从小型可信团队扩大，再重新评估 Cortex Playground 的独立 enable flag 或 route auth。

任何新改动如果改变上述优先级，应先更新 `optimization_review_zh.md`，而不是继续追加新的 Phase 状态文档。