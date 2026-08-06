# VolCurve 优化审阅与实施记录

基线：2026-08-06，`master` 停在 `stopped in phase 4`。本文记录对
`volcurve_comprehensive_optimization_plan.md` 的代码级复核、已经落地的改动，以及仍需完成的验收边界。

## 结论

原计划对优先级的判断基本正确：在继续做页面前，必须先解决非正 IV、重复日期、forward RV 范围、cache 完成顺序和公司行动误标。此次优化没有改写用户提供的计划原文，而是先完成可离线验证的正确性加固，再以 Gate B/C 的 fixture 与 live 证据逐项开放能力。

Phase A、B、C、D 已分别按 Gate A、B、C、D 收口。delta、fixed、listed 已具备严格请求契约、BNP wire serializer、通用坐标 parser、REST/CSV 路由、fixtures、真实 API probe 与动态 Web 页面；Phase D 正等待用户检查。

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
| Phase D：Web MVP | 通过，待用户检查 | 四种动态模式、Compare/Surface、离线图表、表格/CSV、methodology、quality/activity/disclosures 与桌面/移动浏览器检查均通过 |
| Phase E：验证部署 | 未开始 | 定向 secret 检查不能替代完整 Gate |

## 下一实施批次

1. 等待用户检查并批准 Phase D 的使用方式与页面信息密度。
2. Phase E 做独立数值复算、live page/API/CSV 一致性、完整 secret/dependency scan、Docker 与运维说明。
3. 用户在实际使用 Web 后提出的交互调整作为 Phase D 后续修订，不在本阶段预设复杂产品规则。

## 当前验证

```text
python -m pytest -q
86 passed

python -m compileall -q app scripts tests
PASS

git diff --check
PASS
```
