# VolCurve 综合优化实施方案

**项目：** BNP Cortex Vol Analytics  
**仓库：** `pixie26/volcurve`  
**基线日期：** 2026-08-06  
**适用范围：** 当前 Phase 0–3 已完成、Phase 4 开发中的代码基线  
**明确排除：** 自然语言查询、LLM 请求解析、自动交易

---

## 1. 最终判断

当前项目的底层方向正确，Phase 0–3 已经形成一套可继续扩展的基础：

- BNP OAuth2 client-credentials 认证；
- instruments 与 implied-volatility 探针；
- 坐标化解析 volatility matrix；
- raw JSON、Parquet、DuckDB 持久化；
- live / cache / fixture 三种数据路径；
- trailing / forward realized volatility；
- IV−RV、percentile、z-score、correlation；
- 基础数据质量标记和独立 RV 复算。

下一阶段不需要推倒重来。应在现有结构上完成以下三件事：

1. **先修正会影响数值正确性的边界问题；**
2. **完整支持 BNP implied-volatility 的 fixed、listed、delta、K/F、K/S 请求模式；**
3. **完成 REST API 和 Web 页面，并把所有数据异常明确展示给用户。**

---

## 2. 已确认的用户决定

### 2.1 仓库安全

仓库已改为 private。用户确认此前没有向其他人分享，仓库无人关注，也没有已知外部访问或泄密。

因此本方案不再把“仓库转 private”列为阻塞项，也不强制要求仅因短暂公开而轮换凭证。

仍保留以下轻量安全措施：

- 运行一次 Git 全历史 secret scan；
- 确认 `.env`、token、raw 授权行情没有进入 Git；
- BNP 文档只保留在 private repository 或受控内部存储；
- 若扫描发现真实 secret，立即清理历史并轮换该 secret；
- 不在 README、日志、截图、CSV metadata 或前端响应中显示凭证。

### 2.2 Implied-volatility 请求范围

以下模式都属于正式需求，不能简单关闭：

- `relative_to_forward`
- `relative_to_spot_ref`
- `delta`
- `fixed`
- `listed`

实现方式必须是**不同模式对应不同请求模型和动态页面表单**，不能继续由一个宽松模型混合处理所有字段。

### 2.3 非正 IV

当 BNP 返回零或负数 IV 时：

- 该点不得参与 spread、ratio、percentile、z-score、correlation；
- 后端不得静默修正为零、绝对值或极小正数；
- 原始返回值必须保留，便于审计；
- 前端必须明确提示用户哪些日期、哪些坐标出现异常。

### 2.4 Corporate action 与 10% 跳变规则

现有 `|log return| > 10%` 只是一个粗糙的**价格异常跳变探测器**，不是 corporate-action detector。

它不能可靠识别：

- 正常现金分红；
- 小比例拆合股；
- 特别股息；
- ETF distribution；
- 数据源切换或 stale price。

因此必须停止将该规则描述为“已识别 corporate action”。

---

# 3. 目标产品范围

## 3.1 第一版正式功能

### 数据查询

- 搜索 BNP instruments；
- 查询 implied-volatility surface；
- 支持 sliding、fixed、listed maturity；
- 支持 K/F、K/S、delta、absolute strike；
- 支持单点、slice、range；
- 保存 raw API response；
- 保存标准化 observation；
- 持久缓存和可重放。

### 分析

- IV 时间序列；
- trailing RV；
- forward RV；
- IV−RV；
- IV/RV；
- percentile；
- z-score；
- correlation；
- spot；
- forward；
- smile slice；
- term structure。

### 页面

- 动态 query builder；
- 支持能力与有效参数提示；
- 图表；
- 数据表；
- CSV；
- methodology；
- data quality；
- activity / error panel；
- suggested action。

## 3.2 第一版不做

- 自然语言查询；
- LLM；
- 自动生成 BNP request；
- 自动交易；
- 交易信号；
- 多租户权限系统；
- 定时邮件；
- EDSLib calibration；
- EDS surface residual；
- portfolio aggregation。

---

# 4. P0：数据正确性修复

这些事项应在继续开发 Web 页面前完成。

## 4.1 Canonical observation pipeline

当前 parser 可以给 duplicate 和 non-monotonic date 打 flag，但这些数据仍可能进入 RV 计算。

改成明确的处理顺序：

```text
BNP payload
→ Pydantic schema validation
→ coordinate validation
→ observation normalization
→ sort by date
→ duplicate resolution
→ strict monotonicity check
→ numerical validity check
→ analytics
→ cache completed
```

### Duplicate policy

同一日期有多条记录时：

1. 若内容完全一致：保留一条，并标记 `DUPLICATE_IDENTICAL_REMOVED`；
2. 若 snapshot time 不同：按请求的 close/snapshot 规则选择，不能任意取第一条；
3. 若无法判断：hard fail，错误码 `AMBIGUOUS_DUPLICATE_DATE`；
4. 不允许带着冲突 duplicate 继续算 RV。

## 4.2 Cache 状态机

当前风险是上游返回 HTTP 200 后先落盘为 completed，随后 parser 才失败。

改为：

```text
FETCHING
FETCHED
SCHEMA_VALIDATED
NORMALIZED
COMPLETED
```

失败状态：

```text
UPSTREAM_FAILED
INVALID_SCHEMA
PARSE_FAILED
NORMALIZATION_FAILED
STORAGE_FAILED
```

规则：

- raw payload 可以在 `FETCHED` 阶段保存；
- 只有 parser、normalizer、hash 验证均完成后才进入 `COMPLETED`；
- 只有 `COMPLETED` 可以作为 cache hit；
- 失败 payload 保留用于诊断，但不得参与业务查询；
- catalog 保存 normalized error code，不保存未脱敏上游 body。

## 4.3 非正 IV 处理

新增质量标记：

```text
INVALID_IV_ZERO
INVALID_IV_NEGATIVE
SUSPICIOUS_IV_EXTREME
```

标准化 observation 增加：

```python
raw_implied_vol: float | None
implied_vol: float | None
```

处理：

```text
raw > 0 且在合理数值范围：
    implied_vol = raw
raw == 0：
    implied_vol = null
    flag INVALID_IV_ZERO
raw < 0：
    implied_vol = null
    flag INVALID_IV_NEGATIVE
raw 很高但仍可能合法：
    implied_vol = raw
    flag SUSPICIOUS_IV_EXTREME
```

不得：

- clip；
- abs；
- zero-fill；
- 向前填充；
- 用邻近 strike 或 maturity 静默替代。

### 前端展示

出现无效 IV 时：

1. 页面顶部显示 warning banner；
2. 显示异常点数量与日期范围；
3. 图中该点为空，不跨越连接；
4. table 行显示醒目标记；
5. hover 显示 raw IV 和原因；
6. summary 指标排除该点；
7. CSV 同时导出 `raw_implied_vol`、`implied_vol`、`quality_flags`；
8. activity panel 显示：

```text
BNP returned 3 non-positive IV observations.
These observations were excluded from analytics and retained for audit.
Suggested action: inspect dates/coordinates or retry with another convention.
```

## 4.4 Forward RV 获取范围

Trailing 与 forward 不能共用同一 fetch range。

### Trailing

```text
fetch_start = display_start - warmup buffer
fetch_end   = display_end
```

### Forward

```text
fetch_start = display_start
fetch_end   = display_end + future buffer
```

future buffer 初始按：

```text
ceil(window_sessions × 7 / 5) + 10 calendar days
```

然后检查有效 observation 数量：

- 若不足 `window + 1`，继续追加；
- 不超过当前可用数据日期；
- 尚未实现的 forward RV 保持 null；
- 已经有未来数据的历史日期应完整计算，不能机械地让最后 63 个显示日期全部为空。

## 4.5 Summary 的 latest 定义

拆分为：

```text
latestMarketDate
latestIv

latestComparableDate
latestComparableIv
latestComparableRv
latestComparableSpread
```

percentile、z-score、ratio、correlation 使用 valid comparable pairs。

这样 forward RV 页面不会出现：

- 最新 IV 有值；
- 最新 RV 为空；
- 整个 summary 看起来失效。

## 4.6 UTC 和时间语义

内部统一：

- UTC timezone-aware `datetime`；
- `retrieved_at_utc`；
- `source_time` 与 `source_timezone` 分开保存；
- 日期序列保留 BNP business date；
- 前端根据用户时区展示 retrieval time；
- 不使用 naive `datetime.now()` 作为审计时间。

---

# 5. 完整支持 BNP implied-volatility 请求模式

## 5.1 不再使用一个宽松的 ImpliedVolRequest

建立 discriminated union。每种模式只能包含该模式允许的字段。

---

## 5.2 模式 A：Sliding maturity + K/F 或 K/S

```python
class SlidingMoneynessRequest:
    maturityRule: Literal["sliding"]
    strikeRule: Literal[
        "relative_to_forward",
        "relative_to_spot_ref",
    ]
    lowStrike: float
    highStrike: float
    lowMaturity: str
    highMaturity: str
```

适用：

- ATM-forward；
- spot moneyness；
- smile range；
- term range；
- 单点或 surface。

页面字段：

- moneyness convention；
- low/high moneyness；
- low/high tenor；
- single point shortcut。

---

## 5.3 模式 B：Sliding maturity + Delta

```python
class SlidingDeltaRequest:
    maturityRule: Literal["sliding"]
    strikeRule: Literal["delta"]
    lowDeltaStrike: DeltaCode | None
    highDeltaStrike: DeltaCode | None
    lowMaturity: str | None
    highMaturity: str | None
```

DeltaCode 使用 BNP 允许的枚举，例如：

```text
p1.0, p5.0, p10.0, p25.0, p50.0
c50.0, c25.0, c10.0, c5.0, c1.0
```

内部 wire conversion：

```text
p25.0 → p25_0
c10.0 → c10_0
```

页面必须区分：

- put delta；
- call delta；
- ATM 的具体定义；
- low/high 顺序；
- delta convention 来自 BNP API，不由系统自行推测。

---

## 5.4 模式 C：Fixed/List maturity + Absolute strike

```python
class FixedStrikeRequest:
    maturityRule: Literal["fixed", "listed"]
    strikeRule: Literal["fixed"]
    lowFixedStrike: float | None
    highFixedStrike: float | None
    lowFixedMaturity: date | None
    highFixedMaturity: date | None
```

适用：

- 指定实际 expiry date；
- absolute strike；
- listed surface；
- 对具体 option chain 的历史分析。

页面字段：

- maturity mode：fixed theoretical / listed；
- expiry start/end；
- strike start/end；
- exact expiry shortcut；
- exact strike shortcut。

---

## 5.5 模式 D：Fixed/List maturity + Sliding K/F 或 K/S

```python
class ListedMaturityMoneynessRequest:
    maturityRule: Literal["fixed", "listed"]
    strikeRule: Literal[
        "relative_to_forward",
        "relative_to_spot_ref",
    ]
    lowStrike: float
    highStrike: float
    lowFixedMaturity: date | None
    highFixedMaturity: date | None
```

适用：

- 真实 expiry date；
- 但 strike 仍用 K/F 或 K/S 表示；
- 对 listed expiry 的 smile 分析。

---

## 5.6 Wire model 与 domain model 分离

目录建议：

```text
app/domain/vol_requests/
├── base.py
├── sliding_moneyness.py
├── sliding_delta.py
├── fixed_strike.py
├── listed_moneyness.py
└── union.py

app/clients/cortex/
├── wire_models.py
├── serializers.py
└── parser.py
```

原则：

- domain model 采用易读字段；
- wire serializer 负责下划线编码；
- parser 不读取不属于当前模式的字段；
- request hash 使用完整 canonical wire request；
- 每种模式有独立 unit test 与 contract fixture。

---

# 6. Capability registry

增加：

```http
GET /api/v1/capabilities
```

用途：

- 前端不硬编码 BNP 规则；
- 页面只显示当前后端真正支持的选项；
- OpenAPI 版本变更后可以更新 registry；
- 用户可以清楚看到 indicator、tenor、strike 和 mode 的合法范围。

返回示意：

```json
{
  "apiVersion": "1.60.0",
  "maturityModes": ["sliding", "fixed", "listed"],
  "strikeModes": [
    "relative_to_forward",
    "relative_to_spot_ref",
    "delta",
    "fixed"
  ],
  "slidingMaturities": [
    "1W", "2W", "3W", "1M", "2M", "3M",
    "6M", "9M", "12M", "18M", "2Y", "3Y", "5Y"
  ],
  "deltaStrikes": [
    "p10.0", "p25.0", "p50.0",
    "c50.0", "c25.0", "c10.0"
  ],
  "indicators": [
    "implied_vol",
    "realized_vol",
    "spot",
    "forward",
    "iv_minus_rv",
    "iv_divided_by_rv",
    "percentile",
    "zscore",
    "correlation"
  ],
  "rvWindows": [5, 10, 20, 40, 60, 90, 120, 250, 500],
  "rvWindowRange": {
    "minimum": 2,
    "maximum": null,
    "integerOnly": true,
    "nearestSubstitution": false
  },
  "rvAlignments": ["trailing", "forward"],
  "priceAdjustment": "unadjusted"
}
```

Capability registry 可由两部分组成：

1. OpenAPI 静态枚举；
2. 当前项目已实现能力。

只有两者交集出现在前端。

---

# 7. Corporate action 和价格质量方案

## 7.1 移除错误语义

现有：

```text
|log return| > 10%
→ POSSIBLE_CORPORATE_ACTION
```

改为：

```text
RETURN_OUTLIER
```

或：

```text
POSSIBLE_PRICE_ANOMALY
```

原因：

- 大涨大跌不是 corporate action；
- corporate action 可能远小于 10%；
- 10% 只是粗略异常阈值；
- QQQ 除息通常不会触发 10%。

## 7.2 分层质量检测

### Layer 1：结构检查

- missing spot；
- spot ≤ 0；
- duplicate date；
- non-monotonic date；
- matrix mismatch；
- coordinate mismatch；
- stale data；
- missing IV；
- missing forward。

### Layer 2：价格异常检查

同时使用：

- 绝对 log return 阈值；
- rolling median / MAD；
- rolling volatility z-score；
- 与前后日期连续性对比。

输出：

```text
RETURN_OUTLIER
POSSIBLE_STALE_PRICE
POSSIBLE_SOURCE_DISCONTINUITY
```

这些只提示，不自动修正。

### Layer 3：Corporate action

只有在有可信 corporate-action source 时才标记：

```text
CONFIRMED_CASH_DIVIDEND
CONFIRMED_SPLIT
CONFIRMED_SPECIAL_DIVIDEND
CONFIRMED_OTHER_CORPORATE_ACTION
```

数据来源必须是：

- BNP 明确字段；
- 公司许可的 corporate-action 数据库；
- 正式授权的 adjusted close 数据。

Yahoo 可以作为一次性研究验证，不应作为生产依赖。

## 7.3 RV 口径显示

第一版页面必须明确：

```text
Price source: BNP Cortex spot
Price adjustment: unadjusted
Return type: price return
Dividend adjustment: not applied
```

不要再写“corporate action 已自动标记”，除非以后真正接入 corporate-action calendar。

## 7.4 后续可选指标

未来可以增加：

- Raw-price RV；
- Dividend-adjusted RV；
- Total-return RV；
- Parkinson RV；
- Garman–Klass RV；
- Yang–Zhang RV。

第一版仍以 close-to-close raw-price RV 为主。

---

# 8. REST API 完成方案

## 8.1 应增加的文件

```text
app/
├── main.py
├── api/
│   ├── capabilities.py
│   ├── instruments.py
│   ├── vol_compare.py
│   ├── vol_surface.py
│   ├── exports.py
│   ├── errors.py
│   └── health.py
```

## 8.2 接口

```http
GET  /api/v1/capabilities
GET  /api/v1/instruments?q=QQQ
POST /api/v1/vol/compare
POST /api/v1/vol/surface
POST /api/v1/vol/compare.csv
GET  /health/live
GET  /health/ready
```

### `/vol/compare`

主要用于：

- 单个 IV 坐标；
- RV；
- spread；
- time series；
- summary。

### `/vol/surface`

主要用于：

- 多 strike；
- 多 maturity；
- smile；
- term structure；
- heatmap。

不要把所有返回都塞进 `/vol/compare`。

## 8.3 标准化错误响应

```json
{
  "requestId": "abc123",
  "code": "INVALID_IV_OBSERVATIONS",
  "message": "BNP returned 3 non-positive IV observations.",
  "stage": "normalization",
  "affectedObservations": 3,
  "suggestedAction": "Inspect the affected dates and coordinates or retry another convention."
}
```

浏览器不得看到：

- token；
- client secret；
- Authorization；
- BNP raw response body；
- stack trace；
- 本地文件路径。

## 8.4 Activity events

后端为每个请求记录用户可见的低敏事件：

```text
REQUEST_VALIDATED
INSTRUMENT_RESOLVED
CACHE_HIT
UPSTREAM_FETCH_STARTED
UPSTREAM_FETCH_COMPLETED
SCHEMA_VALIDATED
COORDINATES_RESOLVED
INVALID_POINTS_EXCLUDED
ANALYTICS_COMPLETED
CSV_GENERATED
```

前端可以显示“后台做了什么”，但不显示敏感实现细节。

---

# 9. Web 页面设计

## 9.1 Query Builder

页面根据 `/capabilities` 动态展示字段。

### Common

- instrument；
- date range；
- volatility convention；
- maturity mode；
- strike mode；
- layout；
- indicators。

### K/F 或 K/S

- single / range；
- moneyness；
- low/high moneyness；
- tenor；
- low/high tenor。

### Delta

- put/call delta；
- low/high delta；
- tenor range。

### Fixed strike

- exact strike；
- strike range；
- exact expiry；
- expiry range。

## 9.2 Indicator selector

明确告诉用户可选：

- IV；
- RV；
- spot；
- forward；
- IV−RV；
- IV/RV；
- percentile；
- z-score；
- correlation；
- smile；
- term structure。

每个指标旁显示定义，例如：

```text
3M IV — K/F = 100%
RV 63 trading days — trailing
```

不能只写 `IV` 或 `RV`。

## 9.3 Data quality panel

显示：

- 总观测数；
- valid 数；
- excluded 数；
- warning 数；
- 各 flag 数量；
- 受影响日期；
- raw value；
- suggested action。

严重级别：

```text
INFO
WARNING
ERROR
BLOCKING
```

示例：

```text
WARNING
2 observations had negative implied volatility.
They were excluded from spread and percentile calculations.
Dates: 2026-04-12, 2026-04-13
```

## 9.4 Activity / Error panel

用户可以看到：

- 当前阶段；
- live / cache；
- 请求耗时；
- 返回多少日期；
- 是否有异常点；
- 错误原因；
- suggested action；
- request ID。

## 9.5 图表规则

- 无效点不连线；
- hover 显示 quality flag；
- trailing/forward 清楚标注；
- spot 放独立 y-axis 或独立图；
- IV 和 RV 均以百分数展示；
- spread 以 vol points 展示；
- fixed expiry 显示实际日期；
- delta 显示 put/call 符号；
- surface 图明确 axes 和 convention。

---

# 10. HTTP、存储与运行时加固

## 10.1 HTTP client

- FastAPI lifespan 创建共享 `httpx.Client`；
- connection pooling；
- shutdown 关闭；
- 401 最多刷新一次；
- 429 支持秒数和 HTTP-date 两种 `Retry-After`；
- 最大等待上限；
- 5xx bounded retries；
- retry 加 jitter；
- 不自动重试 400、403、422、schema failure。

## 10.2 原子写入

Raw 和 Parquet：

```text
write temp
→ flush
→ fsync
→ atomic replace
```

读取 raw 时：

- 验证 gzip；
- 验证 payload hash；
- hash 不符则 cache invalid；
- catalog 标记 `CORRUPTED_RAW_CACHE`。

## 10.3 并发

MVP：

```text
uvicorn workers = 1
```

原因：

- 单 DuckDB writer；
- 单进程内 token manager；
- 单例 cache client；
- 避免并发重复请求。

同时：

- compare semaphore；
- identical request coalescing；
- 同一 request hash 只允许一个 live fetch。

以后多 worker 时再迁移：

- PostgreSQL catalog；
- shared object storage；
- distributed lock。

---

# 11. 测试方案

## 11.1 Unit tests

### Request models

- 每个模式合法请求；
- forbidden field；
- missing mandatory field；
- wire conversion；
- canonical hash；
- fixed/listed/delta 枚举。

### Parser

- matrix coordinates；
- fixed expiry；
- delta strikes；
- duplicate；
- non-monotonic；
- zero IV；
- negative IV；
- extreme IV；
- missing forward；
- inconsistent axes。

### Analytics

- trailing RV；
- forward RV；
- forward range extension；
- latest comparable；
- excluded invalid points；
- percentile/z-score valid pair policy。

### Storage

- atomic write；
- corrupted gzip；
- hash mismatch；
- failed parse 不成为 completed cache；
- cache state transition。

### HTTP

- token refresh；
- 401；
- 403；
- 429 seconds；
- 429 HTTP-date；
- 5xx retries；
- timeout；
- redaction。

## 11.2 Contract fixtures

分成：

```text
tests/fixtures/schema/
tests/fixtures/market/
tests/fixtures/errors/
```

### Schema fixture

- 保留真实字段结构；
- 数据脱敏；
- 只验证 parsing。

### Market fixture

- 有效交易日；
- 内部一致的 spot/forward/discount/IV；
- 已知 expected RV；
- 支持业务计算测试。

### Error fixture

- negative IV；
- zero IV；
- malformed matrix；
- duplicate conflict；
- missing axes；
- stale date。

## 11.3 API integration tests

Fixture mode 下测试：

- capabilities；
- instruments；
- compare；
- surface；
- CSV；
- health；
- normalized errors；
- data-quality summary。

## 11.4 Live probes

Live probes 不进入 CI，只作为人工 Gate：

- auth；
- instruments；
- K/F；
- K/S；
- delta；
- fixed；
- listed；
- cache；
- 10 日期人工核对。

---

# 12. CI 与安全

建议 GitHub Actions：

```text
pytest
ruff
pyright
pip-audit
gitleaks
fixture API smoke test
```

由于仓库包含 BNP client-confidential 资料：

- CI log 不打印 raw response；
- workflow artifact 不上传 raw data；
- fixture 必须脱敏；
- `.env` 不进入 Actions；
- live credentials 不在普通 CI 使用；
- live probe 在本地或公司受控 runner 手动执行。

---

# 13. 分阶段实施顺序

## Phase A：Correctness hardening

**预计：1–2 天**

完成：

- cache state machine；
- sort/deduplicate；
- invalid IV raw/effective 双字段；
- negative/zero IV flags；
- forward RV fetch extension；
- latest comparable；
- UTC；
- corporate-action 文案修正；
- return outlier 改名；
- 新增单测。

### Gate A

```text
[ ] 非正 IV 不进入任何统计
[ ] 前端所需异常信息已包含在 API response
[ ] duplicate conflict 会 hard fail
[ ] forward RV 能使用 display_end 之后已存在的数据
[ ] bad payload 不会成为 completed cache
```

---

## Phase B：完整 request model

**预计：2–3 天**

完成：

- sliding K/F；
- sliding K/S；
- sliding delta；
- fixed absolute strike；
- listed absolute strike；
- fixed/listed maturity + sliding moneyness；
- serializers；
- capability registry；
- contract fixtures。

### Gate B

```text
[ ] 每种模式都有独立 Pydantic model
[ ] forbidden field 会在本地拒绝
[ ] wire request 与 BNP OpenAPI 一致
[ ] request hash 覆盖所有模式字段
[ ] 真实 API 每种模式至少一次 probe
```

---

## Phase C：REST API

**预计：2–3 天**

完成：

- main；
- capabilities；
- instruments；
- compare；
- surface；
- CSV；
- global errors；
- activity events；
- health；
- API integration tests。

### Gate C

```text
[ ] fixture mode 全接口可用
[ ] live QQQ compare 可用
[ ] live delta/fixed/listed 至少各一个样例可用
[ ] API/CSV 数值一致
[ ] 无敏感信息返回浏览器
```

---

## Phase D：Web MVP

**预计：3–4 天**

完成：

- dynamic query builder；
- indicator selector；
- IV/RV/spot/spread 图；
- smile；
- term structure；
- table；
- CSV；
- methodology；
- quality panel；
- activity/error panel。

### Gate D

```text
[ ] 页面能发现全部已支持 mode
[ ] IV 与 RV 标签完整
[ ] 非正 IV 明确提示
[ ] 无效点不连接、不进入 summary
[ ] 用户能看到后台阶段、错误原因和 suggested action
[ ] 页面明确显示 spot 未复权
```

---

## Phase E：验证与部署

**预计：2–3 天**

完成：

- 10 日期 IV 核对；
- RV 独立复算；
- fixed/delta/listed 样本核对；
- page/API/CSV 一致；
- raw hash；
- secret scan；
- dependency audit；
- Docker；
- single-worker deployment；
- validation report；
- operations runbook。

### Gate E

```text
[ ] 所有核心模式有人工验证样本
[ ] validation_report.md 完成
[ ] secret scan 通过
[ ] private repository 状态确认
[ ] 内网部署说明完成
[ ] raw licensed data retention policy 明确
```

---

# 14. 优先级总结

## 必须先做

1. invalid IV 处理与前端信息契约；
2. cache completed 顺序；
3. duplicate / ordering；
4. forward RV fetch range；
5. 完整 request discriminated union；
6. corporate-action 语义修正。

## 随 Phase 4 一起做

1. capability endpoint；
2. activity/error panel 数据结构；
3. latest comparable summary；
4. standardized errors；
5. shared HTTP client；
6. atomic storage。

## 页面阶段做

1. dynamic controls；
2. explicit IV/RV labels；
3. invalid point visualization；
4. methodology；
5. quality summary；
6. smile / term structure。

## 后续再做

1. licensed adjusted-price RV；
2. confirmed corporate-action calendar；
3. advanced RV estimators；
4. EDS surface overlay；
5. market-coordinate risk；
6. multi-user authentication。

---

# 15. 最终验收定义

项目达到可信内部 MVP，必须同时满足：

```text
[ ] K/F、K/S、delta、fixed、listed 均有正确请求模型
[ ] 不兼容字段组合在本地被拒绝
[ ] matrix 永远按坐标解析
[ ] raw IV 与 effective IV 分开保存
[ ] 零或负 IV 不参与统计
[ ] 页面明确显示零/负 IV、日期、坐标与 suggested action
[ ] duplicate conflict 不进入计算
[ ] trailing 和 forward RV range 正确
[ ] raw spot 未复权在页面明确说明
[ ] 10% 跳变不再称为 corporate action
[ ] 只有可信 corporate-action source 才能标记 confirmed action
[ ] cache 只有在 schema/parse/normalize 完成后才是 completed
[ ] raw 和 normalized 数据可追溯
[ ] API、页面、CSV 数值一致
[ ] fixture CI 通过
[ ] live probe 通过
[ ] secret scan 通过
[ ] repository 保持 private
[ ] 单 worker 内网部署完成
```

---

# 16. 预计剩余时间

| 阶段 | 时间 |
|---|---:|
| Phase A：Correctness hardening | 1–2 天 |
| Phase B：完整 request model | 2–3 天 |
| Phase C：REST API | 2–3 天 |
| Phase D：Web MVP | 3–4 天 |
| Phase E：验证与部署 | 2–3 天 |
| **合计** | **10–15 个工作日** |

若第一版暂缓 smile/surface 页面，仅完成 time-series compare，可压缩至约 **7–10 个工作日**。

---

## 最终实施原则

> 不减少 BNP API 的能力范围，但必须用严格、分模式的数据契约承接这些能力。

> 不隐藏异常数据，也不让异常数据污染统计；原始值留存、有效值置空、前端明确提示。

> 不把普通价格跳变误称为 corporate action；没有可信 corporate-action 数据源时，只能提示 price anomaly。

> 页面不是简单画图，而是同时展示查询定义、数据口径、质量状态、后台执行阶段和可操作的错误建议。
