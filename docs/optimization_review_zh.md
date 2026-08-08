# VolCurve 当前状态、关键决策与 Roadmap

原始优化基线：2026-08-06  
当前修订：2026-08-08  
当前 master 基线：Step 7 historical archive 已 merge

> 本文现在是项目的 **living status / roadmap**。Phase A–D acceptance 与 Phase E validation report 继续保留为带日期的历史验收证据，不再在本文重复完整阶段流水账。文档导航见 [`README.md`](README.md)。

## 一、当前结论

VolCurve 已从早期单坐标 IV/RV prototype 演进为可用的内部 Time Series 波动率研究工作台。当前 correctness 主链路已经基本收口：

- 严格 BNP request contract + serializer/parser；
- IV raw/effective 分离与质量标记；
- trailing/forward RV 与有效 session 边界；
- Compare/Surface/CSV/API；
- Sliding / Listed / Delta / Absolute strike 的明确产品边界；
- 8-chart Time Series、同日 hover、同步 X zoom、board persistence；
- error provenance、single-flight、upstream concurrency limiter；
- rolling 8h request cache；
- revision-aware historical point archive；
- explicit stale fallback。

目前不建议继续堆新的用户功能。下一阶段应先把 Step 7 新增的长期历史资产做成真正可运维、可审计、可恢复的数据层。

## 二、已经冻结的核心语义

### 1. IV / RV 数学与质量边界

- raw IV 保留上游原值；effective IV 只接受正有限值；
- 0、负值、non-finite 不进入 IV/RV analytics；极端正 IV 保留并标记 suspicious；
- RV 使用 close-to-close log return、样本标准差 `ddof=1`、`sqrt(252)` 年化；
- trailing/forward window 按有效 market sessions 计数；未来数据不足时 forward RV 保持 null；
- `|log return| > 10%` 只标记 `RETURN_OUTLIER`，不自动认定 corporate action。

### 2. 坐标原则

- 主 UI maturity：Sliding tenor + Listed expiry；
- Fixed 仍是合法 backend/OpenAPI coordinate，但不是主 indicator builder 普通入口；
- K/F 与 K/S percentage moneyness 分开；
- Delta 只允许 BNP contract 支持的组合；
- Listed expiry + absolute strike 先 discovery 实际 strikes，但仍允许用户输入精确 strike；
- 不存在的 maturity/strike/date 返回缺失或 `NO_DATA`，不做 nearest-coordinate substitution。

### 3. Time Series 产品边界

- 最多 8 个上下排列 chart；
- 每 indicator 独立 instrument / coordinate / enabled state；
- hover 只对齐精确 observation date；
- X zoom 同步，Y axis 独立；
- board 保存配置，不把旧 market response 当作当前数据持久化到浏览器。

完整产品契约见 [`phase_f_compare_indicator_builder_zh.md`](phase_f_compare_indicator_builder_zh.md)。

### 4. Request/cache/upstream

- 相同 request hash single-flight；
- 不同真实 upstream attempts 进程内最多 4 个并发；
- retry 在 backoff 前释放 slot；
- request cache freshness 统一为滚动 8 小时；
- exact 与 covering cache 同时可用时，`retrieved_at` 更新者优先；相同时间才偏好 exact/narrower payload；
- covering cache 不得制造 synthetic narrow `COMPLETED` lifecycle state；
- empty result 在 client/public contract 中保持 `NO_DATA`。

### 5. Historical archive（Step 7）

长期历史库只保存精确单坐标的：

- K/F percentage；
- K/S percentage；
- Delta。

按 `coordinate × observation date` 保存 latest-known observation。重叠请求中新版本覆盖 overlap，未重叠旧历史继续保留；point changed/removed 记录 compact revision delta；晚结束的旧 fetch 不能回滚更新 point。

Absolute/fixed strike、大 listed-strike discovery universe、非精确 range/surface 不进入长期 archive。

若 refresh 因 rate-limit/upstream unavailable/`NO_DATA` 失败，而历史 archive 完整覆盖请求，可返回 stale data；前端必须明确红色 `STALE DATA`。400/401/403/schema/local-contract 错误不允许 stale fallback。

## 三、Stabilization Step 1–7 已完成

| Step | 状态 | 结果 |
|---|---|---|
| 1 | ✅ | 清理 stale Web tests，测试不再绑定旧 UI 文案/selector |
| 2 | ✅ | GitHub Actions：install / compile / Ruff / pytest |
| 3 | ✅ | covering-cache empty slice 统一为 `NO_DATA`；后续 Step 7 又补齐 client lifecycle 边界 |
| 4 | ✅ | Cortex 真实 HTTP attempts process-wide concurrency cap = 4 |
| 5 | ✅ | docs/version 等工程漂移收口；版本唯一来源统一 |
| 6 | ✅ | Bulk Fixed 恢复为明确的 exact request coordinate；raw-error logging 安全边界收紧 |
| 7 | ✅ | 8h cache、historical point archive、revision delta、compaction、stale fallback |

不要再用旧文档中的“5 charts / Listed 手输 + Load/Apply / Fixed 是任意理论日 / historical cache 永久 fresh”等描述判断当前系统。

## 四、当前明确的技术债与风险

### P0 — Historical archive operational durability

这是当前最高优先级。

Step 7 允许在 historical archive 安全覆盖后 compact 旧 request raw，因此：

- `history.duckdb` 已从“普通 cache”变成长期数据资产；
- 不能再假设丢失 history 后一定能从剩余 raw 完整重建；
- 目前缺少独立的 archive migration / integrity audit / coverage inspection / backup-restore verification 工具；
- 生产环境文件级备份方式尚未经过正式恢复演练。

### P1 — Persistent HTTP client lifecycle

当前每次真实 Cortex HTTP attempt 仍创建并关闭一个 `httpx.Client`。correctness 没问题，但损失 connection pooling / keep-alive，并增加 TLS/proxy connection overhead。

后续应改成 CortexClient/lifespan 所有的 persistent client，同时严格验证：

- 线程安全；
- shutdown/close idempotency；
- auth refresh；
- retry/backoff；
- 4-slot limiter；
- Playground/instruments/compare/surface 共用相同连接策略；
- fixture/cache/archive path 不触发网络 client。

### P1 — 正式 deployment gate 尚未完全闭环

- 当前 GitHub repository 为 public；正式团队交付前应切 private；
- 当前开发环境没有形成真实 Docker build + volume restore 的最终验收证据；
- 服务扩大为共享 desk service 时，需要重新评估 Playground enable flag / route auth / proxy ACL；
- multi-worker 仍不支持，不能简单增加 workers 扩容。

### P2 — Historical snapshot semantics

当前 archive 是每个 date 的 latest-known BNP value，不是单一一致 as-of snapshot。因此它适合日常研究，但如果以后做严格回测/模型训练，需要先决定是否增加 snapshot/as-of versioning。当前阶段不要提前实现。

## 五、下一步执行计划

### Step 8 — Historical Archive Operations（下一步）

目标：把 Step 7 的数据模型变成可长期运行的数据资产，而不仅是“测试通过的 cache feature”。

建议拆成三个小 PR：

**8A. Audit / inspection**

- `history_audit`：检查 DuckDB schema、coordinate metadata、point/coverage/revision 基本一致性；
- 验证 coverage interval 不引用不存在/非法 coordinate；
- 检查 point date 是否落在已知 coverage 中；
- 检查 revision old/new provenance 与 current point 的基本关系；
- 输出只包含 counts/hash/date ranges，不泄露行情值。

**8B. Migration / maintenance**

- 扫描现有 completed exact K/F/K/S/Delta request cache；
- 可重跑、幂等地 backfill `history.duckdb`；
- 迁移成功后再允许相应 expired raw 被 compact；
- 提供 dry-run 与 non-destructive default；
- 不自动迁移 absolute/fixed strike surface。

**8C. Backup / restore verification**

- 选择并验证 DuckDB-safe snapshot 方法；
- 在临时目录恢复 snapshot；
- 运行 history audit + raw hash audit + fixture smoke；
- 编写可重复的 disaster-recovery checklist；
- 深度测试 interrupted migration / duplicate migration / corrupted backup / partial restore。

Step 8 完成后，才认为 Step 7 可以进入生产级长期运行。

### Step 9 — Persistent Cortex HTTP Client

在不改变业务语义的前提下引入连接池/keep-alive，目标是降低 repeated TLS/proxy handshake 与资源开销。必须做并发、retry、401 refresh、429、shutdown 和 fixture isolation 深度测试。

### Step 10 — Deployment Release Gate

- 实际 Docker build；
- persistent volume smoke + restore drill；
- repository private；
- reverse proxy / ACL；
- 根据实际用户范围决定 Playground 是否增加独立开关/认证；
- production secret/retention responsibility sign-off。

完成这三步后，再回到新 analytics/UX 功能扩展。

## 六、文档维护规则

为了避免再次出现“代码已经变了、旧 Phase 文档还在描述旧产品”的问题：

- 本文维护**当前状态与 roadmap**；
- `phase_f_compare_indicator_builder_zh.md` 维护**当前 Time Series 产品契约**；
- `operations_runbook_zh.md` 维护**实际部署/恢复操作**；
- `data_retention_policy_zh.md` 维护**licensed data 生命周期责任**；
- Phase A–E acceptance/validation 文件只作为历史证据，不再滚动更新测试数量和 UI 说明；
- 自动测试通过数量以最新 GitHub Actions 为准，不写死在 living docs。