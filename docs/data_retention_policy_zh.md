# Licensed raw data 保留策略

日期：2026-08-07

## 适用范围

`data/raw/` 中的 gzip JSON 是 BNP Cortex 返回的 licensed market data，也是 normalized Parquet 与 DuckDB catalog 的可重建权威源。`data/normalized/` 和 `data/catalog.duckdb` 同样按内部行情衍生数据处理。

## 当前政策

- 数据只保存在运行主机或经批准的加密持久卷，不进入 Git、Docker image、公开 artifact、聊天记录或普通 CI log。
- 当前应用**不自动过期或删除 raw data**。在数据负责人依据 BNP 合约确认具体期限前，采用“保留但不外传”的保守策略。
- 备份、复制到共享盘或跨区域传输必须先由数据负责人确认授权范围；未获确认时默认禁止。
- 访问仅限获 BNP entitlement 且有本项目业务需要的内部用户；部署目录和备份应使用最小权限。
- 终止 entitlement、人员离职、主机退役或收到数据负责人删除指令时，必须同时处理 raw、normalized、DuckDB、备份和临时导出，不能只删除其中一层。
- 删除属于不可逆操作，执行前必须列出精确目标、获得数据负责人批准，并保存不含行情值的删除清单和时间；本项目目前不提供自动删除命令。

## 上线前责任

生产负责人必须把 BNP 合同要求映射为明确的保留期限、备份范围和删除 SLA。该外部合规决定不能由应用代码推断；在确认前不得宣称部署已满足合同层面的 retention 要求。
