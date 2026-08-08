# Licensed market data 保留与生命周期策略

初版日期：2026-08-07  
当前修订：2026-08-08

## 适用范围

本政策覆盖所有由 BNP Cortex licensed market data 直接产生或可反推出行情的本地数据，包括：

- `data/raw/`：按 request 保存的 gzip JSON response；
- `data/normalized/`：按 request 保存的 normalized Parquet；
- `data/catalog.duckdb`：request cache metadata / hash / lifecycle state；
- `data/history.duckdb`：精确 K/F%、K/S%、Delta 时间序列的 latest-known historical points、coverage metadata 与 revision deltas；
- 备份、临时导出以及运维过程中产生的含行情副本。

这些数据都不得因为“已经 normalized”或“只剩 revision”就被视为非 licensed/internal market data。

## 应用内部 lifecycle 与合同 retention 必须分开

Step 7 之后，应用会自动进行**技术性 cache compaction / expiry cleanup**：

- 成功 request cache freshness 为滚动 8 小时；
- 同一 coordinate 的较新 request 完整覆盖较旧 request 时，旧 raw/parquet/catalog cache 可被删除；
- 精确 K/F%、K/S%、Delta 序列在 historical archive 已安全覆盖后，过期 request files 可清理；
- absolute/fixed strike、大 listed-strike universe 和非精确 surface/range 不进入长期历史点库，主要按短期 request-cache 生命周期管理。

这类删除的目的是消除冗余 request cache，**不等同于根据 BNP 合同执行最终 retention/deletion policy**。应用不能自行推断合同要求保留多久，也不能因为代码允许 compact 就宣称满足合同层面的删除义务。

反过来，Step 7 之后也不能继续假设“只保留 raw 就能重建全部数据”：一旦旧 exact-series raw 被安全 compact，`history.duckdb` 中的 latest-known points 与 revision metadata 就成为独立的长期数据资产，需要单独保护和备份。

## 当前数据治理规则

- 数据只保存在运行主机或经批准的加密持久卷，不进入 Git、Docker image、公开 artifact、聊天记录或普通 CI log。
- 访问仅限拥有相应 BNP entitlement 且有本项目业务需要的内部用户；部署目录、备份和导出使用最小权限。
- 备份、共享盘复制、跨主机或跨区域传输必须先确认授权范围；未确认时默认禁止。
- 不允许为了节省空间绕过应用内置的“archive coverage / newer version / completed request”条件直接手工删 raw、Parquet、catalog 或 history rows。
- 终止 entitlement、人员离职、主机退役或收到数据负责人删除指令时，必须同时评估 raw、normalized、catalog、history、备份和临时导出，不能只删除其中一层。
- 合同/合规要求的不可逆删除应由数据负责人批准，并保存**不含行情值**的删除范围、时间和执行结果；应用内部自动 cache compaction 不替代该审批流程。

## 备份责任

当前至少应把整个 `data/` 持久卷作为一个一致的数据资产管理。尤其注意：

- `history.duckdb` 不能再被视为可随时从 raw 完整重建的普通 cache；
- `catalog.duckdb` 与 request files 可在一定程度上重新拉取/重建，但历史 revision provenance 不能假设能从当前 Cortex 再现；
- 备份恢复后必须先执行完整性检查，再重新开放查询；具体操作见 [`operations_runbook_zh.md`](operations_runbook_zh.md)。

在下一工程步骤完成 historical archive audit/backup tooling 前，不应把“已有持久卷”视为完整的 disaster-recovery 证据。

## 上线前外部责任

生产负责人必须把 BNP 合同要求映射为明确的：

- retention period；
- backup scope；
- geographic / sharing constraints；
- entitlement termination handling；
- deletion SLA 与审批/留痕方式。

这些是外部合同和治理决定，不能由应用代码推断。在确认前，不得宣称部署已经满足 BNP 合同层面的 retention 要求。