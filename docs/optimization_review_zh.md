# VolCurve 当前状态、关键决策与 Roadmap

原始优化基线：2026-08-06  
当前修订：2026-08-09  
当前 master 基线：Step 7 historical archive + Frontend 7.5 A–G 已完成

> 本文是项目的**唯一 living status / technical debt / roadmap**。Phase A–D acceptance 与 Phase E validation report 保留为带日期的历史验收证据；Time Series 产品契约、前端测试边界、运维与数据治理分别由专门文档维护。文档导航见 [`README.md`](README.md)。

## 一、当前结论

VolCurve 已从早期单坐标 IV/RV prototype 演进为可用的内部 Time Series 波动率研究工作台。当前 correctness 主链路已经形成可执行 Gate，不再主要依赖人工验证：

- 严格 BNP request contract + serializer/parser；
- IV raw/effective 分离与质量标记；
- trailing/forward RV 与有效 session 边界；
- Compare/Surface/CSV/API；
- Sliding / Listed / Delta / Absolute strike 的明确产品边界；
- 8-chart Time Series、同日 hover、同步 X zoom、board persistence；
- error provenance、single-flight、upstream concurrency limiter；
- rolling 8h request cache；
- revision-aware historical point archive；
- explicit stale fallback；
- Time Series pure core + Node 数值 execution tests；
- Playwright Chromium runtime tests；
- CI enforcement；
- 前端从单体 `compare-builder.js` 渐进拆分为 core / workspace / request / render / controller。

**当前不建议继续堆新的 analytics/UX 功能。** 下一阶段应该先把 Step 7 新增的长期历史资产做成真正可运维、可审计、可恢复的数据层。

## 二、已经冻结的核心语义

### 1. IV / RV 数学与质量边界

- raw IV 保留上游原值；effective IV 只接受正有限值；
- 0、负值、non-finite 不进入 IV/RV analytics；极端正 IV 保留并标记 suspicious；
- RV 使用 close-to-close log return、样本标准差 `ddof=1`、`sqrt(252)` 年化；
- trailing/forward window 按有效 market sessions 计数；未来数据不足时 forward RV 保持 null；
- `|log return| > 10%` 只标记 `RETURN_OUTLIER`，不自动认定 corporate action。

### 2. 坐标原则

- 主 UI maturity：Sliding tenor + Listed expiry；
- Fixed 仍是合法 backend/OpenAPI coordinate，并用于 Bulk Maturity 等明确场景，但不是主 indicator builder 普通入口；
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

### 4. Time Series statistics / derived ownership

Frontend 7.5 后，Time Series 用户可见 range statistics 与 browser-derived series 的 canonical implementation 为：

```text
app/web/compare-core.js
```

它负责：

- `summarizeSeries`；
- mean / quantile / sample std；
- skew / kurtosis；
- autocorrelation；
- 1D / 5D / 20D / 60D change；
- percentile / z-score；
- A+B / A-B / A×B / A÷B；
- `coordinateSignature`；
- `boardSignature` / stable serialization。

规则冻结：

- pure core 不依赖 DOM / fetch / localStorage / mutable UI state；
- Browser production 与 Node tests 执行同一份 production file；
- missing/non-finite 不做 zero-fill；
- derived series 只在共同 observation dates 计算；divide-by-zero 保持 null；
- repeated max/min 的日期与 `sessionsSinceMax/Min` 使用**最近一次**达到极值的 observation。

`app/analytics/statistics.py` **保留**：consumer audit 确认其仍被 `AnalyticsEngine.run_compare` 使用并支撑公开 `CompareSummary` API contract。这里的目标不是“只留一种语言”，而是把前端 Time Series 与后端 API 的 ownership 分清。

详细测试/架构边界见 [`frontend_testing_zh.md`](frontend_testing_zh.md)。

### 5. Request/cache/upstream

- 相同 request hash single-flight；
- 不同真实 upstream attempts 进程内最多 4 个并发；
- retry 在 backoff 前释放 slot；
- request cache freshness 统一为滚动 8 小时；
- exact 与 covering cache 同时可用时，`retrieved_at` 更新者优先；相同时间才偏好 exact/narrower payload；
- covering cache 不得制造 synthetic narrow `COMPLETED` lifecycle state；
- empty result 在 client/public contract 中保持 `NO_DATA`。

### 6. Historical archive（Step 7）

长期历史库只保存精确单坐标的：

- K/F percentage；
- K/S percentage；
- Delta。

按 `coordinate × observation date` 保存 latest-known observation。重叠请求中新版本覆盖 overlap，未重叠旧历史继续保留；point changed/removed 记录 compact revision delta；晚结束的旧 fetch 不能回滚更新 point。

Absolute/fixed strike、大 listed-strike discovery universe、非精确 range/surface 不进入长期 archive。

若 refresh 因 rate-limit/upstream unavailable/`NO_DATA` 失败，而 historical archive 完整覆盖请求，可返回 stale data；前端必须明确红色 `STALE DATA`。400/401/403/schema/local-contract 错误不允许 stale fallback。

## 三、已完成的工程收口

### Stabilization Step 1–7

| Step | 状态 | 结果 |
|---|---|---|
| 1 | ✅ | 清理 stale Web tests，测试不再绑定旧 UI 文案/selector |
| 2 | ✅ | 建立 GitHub Actions 基础工程 Gate |
| 3 | ✅ | covering-cache empty slice 统一为 `NO_DATA`；后续 Step 7 补齐 client lifecycle 边界 |
| 4 | ✅ | Cortex 真实 HTTP attempts process-wide concurrency cap = 4 |
| 5 | ✅ | docs/version 等工程漂移收口；版本唯一来源统一 |
| 6 | ✅ | Bulk Fixed 恢复为明确 exact request coordinate；raw-error logging 安全边界收紧 |
| 7 | ✅ | 8h cache、historical point archive、revision delta、compaction、stale fallback |

### Frontend 7.5 A–G

| 子项 | 状态 | 最终结果 |
|---|---|---|
| 7.5A Pure Core Extraction | ✅ | `compare-core.js` 成为唯一 Time Series pure-core implementation |
| 7.5B Numerical JS Unit Tests | ✅ | production core 直接对 independent Python oracle；tie policy 已冻结 |
| 7.5C Browser Runtime / Playwright | ✅ | 真实 Chromium boot / interaction / request serialization smoke |
| 7.5D Remove pseudo-tests | ✅ | Python Web tests 回归静态 product/asset contract，不再用字符串断言冒充行为测试 |
| 7.5E CI Enforcement | ✅ | Python + Node + Chromium + secret/diff checks 进入 PR / master Gate |
| 7.5F Statistics/API ownership audit | ✅ | Time Series 前端 canonical core；后端 `CompareSummary` consumer 保留 |
| 7.5G Split `compare-builder.js` | ✅ | workspace / request / render / controller 渐进拆分，并有 architecture guardrails |

最终前端边界：

```text
compare-core.js
  pure statistics / derived / signatures
        ↓
compare-workspace.js
  workspace / boards / bulk / persistence
        ↓
compare-request.js
  exact request / fetch / series resolution
        ↓
compare-render.js
  DOM / Plotly / details / statistics table
        ↓
compare-builder.js
  thin bootstrap / orchestration
```

不要再用旧文档中的“5 charts / Listed 手输 + Load/Apply / Fixed 是任意理论日 / historical cache 永久 fresh / 3000+ 行 builder 主要靠人工验收”等描述判断当前系统。

## 四、当前自动验证 Gate

每个 PR 与每次 push 到 `master` 的 CI 链路为：

```text
Python compile
→ Ruff
→ pytest
→ Node unit / architecture tests
→ Playwright Chromium smoke
→ secret scan
→ git diff --check
```

职责边界：

- **pytest**：backend/domain/storage/API/integration contract；
- **Node**：Time Series pure math、derived semantics、signature semantics、frontend architecture；
- **Playwright**：真实浏览器 boot、interaction、Plotly/statistics render、request serialization、runtime exception；
- **Python Web static tests**：offline assets、required controls、security/disclosure、exact-coordinate product semantics；
- **production operations Gate**：licensed persistent volume 上的 raw/history audit、backup/restore drill，不能在没有真实数据的 GitHub runner 上伪造通过。

Living docs 不维护固定 test count，以最新 green workflow 为准。

## 五、当前明确的技术债与风险

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

## 六、下一步执行计划

### Step 8 — Historical Archive Operations（现在开始）

目标：把 Step 7 的数据模型变成可长期运行的数据资产，而不仅是“测试通过的 cache feature”。

建议仍拆成三个小 PR，不做 big-bang：

#### 8A. Audit / inspection

- `history_audit`：检查 DuckDB schema、coordinate metadata、point/coverage/revision 基本一致性；
- 验证 coverage interval 不引用不存在/非法 coordinate；
- 检查 point date 是否落在已知 coverage 中；
- 检查 revision old/new provenance 与 current point 的基本关系；
- 输出只包含 counts/hash/date ranges，不泄露行情值；
- 输出应适合 CI synthetic fixture 与 production persistent-volume 两种模式。

**Exit criteria**：可对一个 history DB 给出机器可判定的 pass/fail，并能定位损坏类别而不泄露 licensed values。

#### 8B. Migration / maintenance

- 扫描现有 completed exact K/F/K/S/Delta request cache；
- 可重跑、幂等地 backfill `history.duckdb`；
- 迁移成功后再允许相应 expired raw 被 compact；
- 提供 dry-run 与 non-destructive default；
- 不自动迁移 absolute/fixed strike surface；
- interrupted migration / duplicate migration 必须可安全重跑。

**Exit criteria**：同一数据集重复执行结果不漂移；失败不会留下“看起来成功但 coverage 不完整”的半状态。

#### 8C. Backup / restore verification

- 选择并验证 DuckDB-safe snapshot 方法；
- 在临时目录恢复 snapshot；
- 运行 history audit + raw hash audit + fixture smoke；
- 编写可重复的 disaster-recovery checklist；
- 深度测试 interrupted migration / corrupted backup / partial restore；
- 明确 backup retention 与 licensed-data responsibility 的交界。

**Exit criteria**：能从备份恢复到新目录，审计通过，服务 fixture smoke 可启动，并有可重复记录的恢复步骤。

**Step 8 完成后，才认为 Step 7 historical archive 具备生产级长期运行条件。**

### Step 9 — Persistent Cortex HTTP Client

在不改变业务语义的前提下引入连接池/keep-alive，目标是降低 repeated TLS/proxy handshake 与资源开销。必须做并发、retry、401 refresh、429、shutdown 和 fixture isolation 深度测试。

原则：先加 lifecycle tests，再改 transport ownership；不要把性能优化和 request semantics 改动混在同一个 PR。

### Step 10 — Deployment Release Gate

- 实际 Docker build；
- persistent volume smoke + restore drill；
- repository private；
- reverse proxy / ACL；
- 根据实际用户范围决定 Playground 是否增加独立开关/认证；
- production secret/retention responsibility sign-off。

完成 Step 8–10 后，再回到新 analytics/UX 功能扩展。

## 七、明确不做的事情

当前阶段不做：

- 为了“代码看起来统一”删除仍被 backend consumer 使用的 Python statistics；
- 重新把 UI behavior 塞回 Python 源码字符串断言；
- 在没有 execution tests 的情况下 big-bang 重写前端；
- 为了性能提前改变 exact-coordinate、stale fallback、single-flight、retry 或 concurrency semantics；
- 在 Step 8 前把 historical archive 当成已完成 disaster-recovery 的长期权威数据源；
- 提前实现严格 as-of snapshot/versioned backtest store。

## 八、文档维护规则

为了避免再次出现“代码已经变了、旧 Phase 文档还在描述旧产品”的问题：

- 本文维护**当前状态 / technical debt / roadmap**；
- `phase_f_compare_indicator_builder_zh.md` 维护**当前 Time Series 产品契约**；
- `frontend_testing_zh.md` 维护**前端代码 ownership / test boundary / refactor guardrails**；
- `operations_runbook_zh.md` 维护**实际部署/恢复操作**；
- `data_retention_policy_zh.md` 维护**licensed data 生命周期责任**；
- Phase A–E acceptance/validation 文件只作为历史证据，不滚动更新测试数量和 UI 说明；
- 自动测试通过数量以最新 GitHub Actions 为准，不写死在 living docs；
- roadmap 发生变化时优先更新本文，不新增另一份“当前状态总表”。