# VolCurve 优化审阅与实施记录

基线：2026-08-06，`master` 停在 `stopped in phase 4`。本文记录对
`volcurve_comprehensive_optimization_plan.md` 的代码级复核、已经落地的改动，以及仍需完成的验收边界。

## 结论

原计划对优先级的判断基本正确：在继续做页面前，必须先解决非正 IV、重复日期、forward RV 范围、cache 完成顺序和公司行动误标。此次优化没有改写用户提供的计划原文，而是先完成可离线验证的正确性加固，再以 Gate B/C 的 fixture 与 live 证据逐项开放能力。

Phase A、B、C、D、E 已分别收口。delta、fixed、listed 已具备严格请求契约、BNP wire serializer、通用坐标 parser、REST/CSV 路由、fixtures、真实 API probe 与动态 Web 页面。Phase E 已完成独立数值复算、安全/依赖审计、raw hash、single-worker runtime 和运维文档。Phase F1 正在把 Compare 改造成“全局标的/日期 + 可组合 indicator + 单一时间轴”；Surface 和结果信息密度留在后续批次。

## 已核实的基线

- Phase 0–3 的六个历史提交和探针/fixture 均存在；Phase 4 只有 health、响应模型和辅助脚本的半成品。
- 优化前 21 个单元测试通过，但没有导入 DuckDB，因此没有覆盖真实 cache catalog。
- README 状态落后于代码：Phase 3 已完成，却仍显示未完成。
- 本地 Cortex OpenAPI 版本为 1.60.0；请求组合表与字段定义是本次请求模型的主依据。
- 定向 Git 历史检查未发现 `.env`、`data/`、私钥路径，也未发现当前 client ID/secret 的值；这不替代最终 Gate 的 gitleaks 全历史扫描。

## 已实施

### 数值和观测正确性

- `raw_implied_vol` 保留 BNP 原值，`implied_vol` 只保留可用于计算的正有限值。
- 零、负数、非有限和极端正 IV 使用不同质量标记；无效值不会进入 spread、ratio、percentile、z-score 或 correlation。
- 输入先做 schema validation，再排序和去重。完全相同的重复项保留一条并标记；同日冲突观测以 `AMBIGUOUS_DUPLICATE_DATE` hard fail。
- `|log return| > 10%` 改名为 `RETURN_OUTLIER`，不再声称识别了 corporate action。
- summary 分离最新市场日、最新有效 IV 日和最新 IV/RV 可比日，解决 forward RV 尾部为空时 summary 失效的问题。
- 新增 trailing/forward 独立 fetch-range 计算；compare service 会检查最后展示日之后的有效价格数，不足 `window + 1` 时继续追加，并在达到可用日上限或安全请求上限时保留 null。
- cache 成功路径显式经过 `FETCHED → SCHEMA_VALIDATED → NORMALIZED → COMPLETED`，失败状态不会被 completed 覆盖。
- API response contract 增加数据质量汇总、异常日期范围、排除策略和低敏 activity event；逐点仍保留 raw/effective IV 与 flags。

### 请求契约

- 增加四类互斥 Pydantic 模型：sliding moneyness、sliding delta、fixed/listed absolute strike、fixed/listed maturity + sliding moneyness。
- 所有模型 `extra="forbid"`；模式不兼容字段在本地拒绝。
- domain 使用 `p25.0` 等可读值，serializer 才转换成 BNP 的 `p25_0`。
- canonical request hash 覆盖完整 wire body 和 API version。

### Cache、存储和时间语义

- raw fetch 后先记录 `FETCHED`，只有 schema/parse/normalize/Parquet 全部成功后才记录 `COMPLETED`。
- 失败状态和 normalized error code 写入 DuckDB；只有 `COMPLETED` 可命中缓存。
- cache read 校验 gzip/JSON 和 payload hash，损坏缓存标记为 `CORRUPTED_RAW_CACHE` 后失效。
- raw gzip 与 normalized Parquet 使用同目录临时文件、flush/fsync 和 atomic replace。
- retrieval time 改用 UTC aware datetime；旧 naive catalog 行按 UTC 兼容解释。

### HTTP 和 API 骨架

- `Retry-After` 同时支持秒数和 HTTP-date，等待上限 60 秒；指数退避增加 jitter。
- 新增 `app.main:app`、`GET /api/v1/capabilities` 和既有 health 路由装配。
- capability payload 同时列出 enabled 与 pending mode，前端不得把“已有请求模型”误当成“端到端已支持”。

## 对原计划的修订意见

1. **不要把示例类的字段全视为必填。** OpenAPI 1.60.0 明确允许 fixed/listed 的 strike 和 expiry 上下界为空，表示返回该方向全部可用坐标。delta 的表格也把上下界列为 optional；本地模型应允许省略，但必须拒绝跨模式字段。
2. **Capability registry 必须表达成熟度。** 仅返回枚举会让页面提前开放未完成的模式。当前响应增加 `enabled` 和 `reason`，Web 只渲染 enabled 交集。
3. **Forward RV 不能只加固定日历 buffer。** 已由 compare service 按有效 observation 数继续追加；连续空区间会指数扩大查询跨度，并设 12 次安全上限，结果不足时保持 null 并显式报告 coverage 未完成。
4. **请求模型完成不等于 BNP 模式完成。** 每个模式还需要 response axis/parser、contract fixture、live probe 和页面标签四项证据。
5. **source time 不应靠字符串拼接推断时区。** 当前同时保留 `source_time` 与 `source_timezone`；只有在确认 BNP timezone 格式后才生成可比较的 instant。
6. **先完成 compare service，再做 Web。** 目前最短关键路径是 fetch-range orchestration → compare/surface API → fixture integration tests → live probes → 页面，不能跳过中间层直接画图。
7. **安全 Gate 要区分定向检查和正式扫描。** 本次结果只能证明当前已知凭证和敏感路径未命中；最终仍需 gitleaks、dependency audit 和受控 runner 验证。

## Gate 现状

| Gate | 状态 | 说明 |
|---|---|---|
| Phase A：invalid IV | 通过 | raw/effective 分离并有回归测试 |
| Phase A：duplicate | 通过 | identical 去重、conflict hard fail |
| Phase A：cache completed 顺序 | 通过 | DuckDB 状态测试覆盖 parse failure |
| Phase A：forward range | 通过 | compare service 自动追加并测试 availability cap/连续空区间边界 |
| Phase A：前端异常契约 | 通过 | response schema 含 raw/effective、flags、quality summary、warning 与 activity；路由属于 Phase C |
| Phase B：完整请求模式 | 通过 | 模型、serializer、parser、fixtures、disclosures 与七组 live probe 均通过 |
| Phase C：REST API | 通过 | 全接口、统一 errors/activity、fixture integration、live delta/fixed/listed 与 CSV 一致性均通过 |
| Phase D：Web MVP | 技术 Gate 通过，UX 待修订 | CSV 位置通过；absolute-strike 模式已增加按观察日发现实际 listed expiry/有效 strike；Compare/Surface 入口、字段结构和信息密度待 Phase E 后 revisit |
| Phase E：验证部署 | 通过 | 10 日期 IV、独立 RV、live 核心模式、API/CSV、raw hash、secret/dependency audit、private repo、single-worker 与文档均通过；Docker build 待部署主机复验 |

## 下一实施批次

1. Phase F1：验收 Compare 的最多 5 个上下同步坐标、每 indicator 独立标的/坐标、同日 hover、矩形 zoom、持久化/启停/删除、maturity/strike 分步选择，以及逐 indicator 数据表、方法、质量、activity、disclosures 和 CSV。
2. Phase F2：在 F1 通过后再根据实际使用反馈调整结果区信息密度与层级；跨页面重开保存已按用户决定在 F1 完成。
3. 最近坐标只允许作为实际返回轴的参考提示；任何 UI 修订都不得改变“不替代精确请求”的语义。
4. Listed 坐标发现继续使用单日、无边界的 BNP `fixed maturity + fixed strike` Surface；expiry 和 strike 均不自动选择，只有用户点击应用才写入草稿。
5. 在实际部署主机执行 Docker build、容器 health 与持久卷复验。

## 当前验证

```text
python -m pytest -q
96 passed

python -m compileall -q app scripts tests
PASS

git diff --check
PASS
```
