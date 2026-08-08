# Cortex Vol Analytics

内部波动率分析 Web 工具，数据源为 BNP Paribas Cortex DataHub API。拉取隐含波动率（IV）、Spot、Forward，并计算已实现波动率（RV）、IV−RV、分位数、z-score、相关性等研究指标，提供 REST API 与单页 Web 工作台。

## 技术栈

- **Python ≥ 3.11**
- **FastAPI + Uvicorn** — REST API
- **httpx** — Cortex DataHub 客户端、认证、重试与并发控制
- **pandas + PyArrow + DuckDB** — analytics、request cache、历史点库与 revision metadata
- **Plotly** — 离线 vendor bundle，不走 CDN
- **Node.js + `node:test`** — 前端 pure-core 数值与架构执行测试
- **Playwright + Chromium** — 真实浏览器行为 smoke tests
- **pytest + Ruff + GitHub Actions** — 后端/API/工程质量 Gate

## 目录结构

```text
app/
  clients/cortex/   # Cortex 认证、HTTP client、serializer/parser、错误处理
  domain/           # 请求、观测、响应等内部数据模型
  storage/          # raw/normalized request cache、catalog、historical point archive
  analytics/        # RV、后端 CompareSummary、质量标记与统计
  security/         # 日志脱敏
  web/
    compare-core.js       # Time Series canonical pure core
    compare-workspace.js  # workspace / board / bulk / persistence
    compare-request.js    # exact request / fetch / series resolution
    compare-render.js     # DOM / Plotly / details / statistics rendering
    compare-builder.js    # thin bootstrap/controller
    app.js                # Surface / shared page logic
  config.py
  version.py        # 应用/package 版本唯一来源
scripts/            # live probe、审计与验证脚本
tests/
  js/               # production pure-core / architecture execution tests
  browser/          # Playwright Chromium runtime tests
  fixtures/         # 脱敏离线响应样本
schemas/            # Cortex OpenAPI 规范
docs/bnp/           # 离线 BNP 官方文档与 SDK 源码
data/               # gitignored：raw、normalized、catalog.duckdb、history.duckdb
```

文档入口见 [`docs/README.md`](docs/README.md)。前端 correctness / module boundary 见 [`docs/frontend_testing_zh.md`](docs/frontend_testing_zh.md)。

## 配置与启动

复制 `.env.example` 为 `.env`：

```text
BNP_CLIENT_ID=
BNP_CLIENT_SECRET=
BNP_TOKEN_URL=https://api.cib.bnpparibas.com/oauth2/v1/token
BNP_BASE_URL=https://api.cib.bnpparibas.com/gm-cortex-datahub
CORTEX_MODE=live        # live | fixture
```

`.env` 与 `data/` 均不得提交 Git。凭据不落盘、不进日志；token 仅在内存缓存。

PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

浏览器访问 `http://127.0.0.1:8000/`。常用 REST 入口包括 `capabilities`、`instruments`、`vol/compare`、`vol/surface`、`vol/compare.csv`、Cortex Playground 与 health。

## 当前 Time Series 产品语义

主 indicator builder 的普通 maturity 入口只有：

- **Sliding tenor**：例如 `1M`、`3M`；
- **Listed expiry**：按 instrument + observation date 自动 discovery 实际 listed expiries，再选择精确 expiry。

`fixed` maturity 仍保留在 backend/OpenAPI/legacy 兼容层中，并用于 Bulk Maturity 等明确场景，但不是主 indicator builder 的普通入口，也不代表任意日历日期存在插值点。

Strike 支持：

- K/F percentage moneyness；
- K/S percentage moneyness；
- Delta（只开放合法组合）；
- Absolute strike。Listed expiry + absolute strike 会按 observation date + expiry 自动 discovery 实际 strikes，同时允许自由输入；不存在的 strike/expiry 不会被替换成最近值。

Time Series 最多支持 **8 个**上下排列坐标；每个 indicator 独立保存 instrument、坐标与启用状态。跨图 hover 只对齐同一个**精确 observation date**，不前填、不插值、不选择最近交易日。完整产品契约见 [`docs/phase_f_compare_indicator_builder_zh.md`](docs/phase_f_compare_indicator_builder_zh.md)。

## 前端 correctness 与代码边界

7.5 已关闭。Time Series 前端不再依赖“3000+ 行单体 JS + 人工验证”的模式：

- `compare-core.js` 是用户可见 range statistics、derived arithmetic、coordinate/board signatures 的唯一前端实现；
- Browser production 与 Node tests 直接执行同一份 production core，不存在源码 extraction seam；
- repeated max/min 的日期与 `sessionsSinceMax/Min` 使用**最近一次**达到极值的 observation；
- Python Web tests 只保留适合静态检查的 product/asset contracts；
- Chromium Playwright 负责页面 boot、真实 interaction、request serialization 与 runtime error 检查；
- architecture tests 防止 pure logic 重复和 `compare-builder.js` 重新长回单体文件。

后端 `app/analytics/statistics.py` 仍被 `AnalyticsEngine.run_compare` / `CompareSummary` API contract 使用，因此保留；它与 Time Series browser-derived statistics 的职责边界已经明确，而不是为了“单一语言”强行删除真实 backend consumer。

## 数据与 cache 语义

当前数据层分成两层：

1. **Request cache**：raw gzip + normalized parquet + `catalog.duckdb`。成功 request 的 freshness 统一为滚动 **8 小时**；过期后下一次使用会尝试重新请求 Cortex。
2. **Historical point archive**：`history.duckdb`。对精确单坐标的 **K/F %、K/S % 与 Delta** 时间序列保存 `coordinate × observation date` 的 latest-known point，并记录轻量 revision delta。

exact 与 covering cache 同时可用时，以 `retrieved_at` 更新的 BNP 版本优先；只有时间相同时才优先 exact/更窄 payload。新的成功 request 完整覆盖旧 request 时，旧 request cache 可以被 compact，因此 **Step 7 之后不能再把 `data/raw/` 描述为整个系统唯一可重建权威源**。

Absolute/fixed strike、大 listed-strike universe、非精确 range/surface 不进入长期历史点库，只使用 request cache。

当 refresh 因 429、上游不可用或 `NO_DATA` 失败，而历史点库完整覆盖请求时，可以返回明确标记的 stale fallback；页面会显示红色 `STALE DATA`，并披露最近成功获取时间、刷新尝试时间和失败原因。400/401/403/schema/local-contract 错误不得被 stale data 掩盖。

## Cortex 请求稳定性

- 相同 request hash：single-flight 合并为一次 upstream call；
- 不同真实 HTTP attempts：进程内最多 **4 个**同时执行；
- cache/archive/fixture path 不占 upstream slot；
- retry 在 backoff 前释放 slot；
- 当前正式部署约束为 `--workers 1`。

## 计算口径

- **RV**：`r_t = log(S_t/S_{t-1})`，样本标准差 `ddof=1`，`√252` 年化；
- trailing RV 的窗口严格按有效 session 计数；forward RV 需要未来有效 observation，尾部不足时保持 null；
- raw IV 保留上游值；非正/非有限 IV 的 effective value 置空并从 analytics 排除；极端正 IV 保留但标记 suspicious；
- 所有 maturity/strike 都坚持精确坐标原则，不做 silent nearest-coordinate replacement。

## 当前状态（2026-08-09）

- ✅ Phase 0–E：认证、严格请求契约、parser、IV/RV analytics、API、Web、live 数值验证与基础部署 Gate；
- ✅ Phase F Time Series：8-chart 工作台、独立 instrument、同日 hover、同步 X zoom、编辑/复制/启停、统计与 board persistence；
- ✅ Listed expiry / absolute strike discovery：observation-date 驱动，并有异步 race guard；
- ✅ Stabilization Step 1–7：测试/CI、`NO_DATA`、upstream concurrency、版本/文档、Bulk Fixed、8h cache、revision-aware archive、compaction、stale fallback；
- ✅ Frontend 7.5 A–G：pure core、数值 execution tests、Playwright、去伪行为测试、CI enforcement、statistics ownership audit、模块化拆分；
- 🚧 **下一优先级：Step 8 Historical Archive Operations** — migration / integrity audit / coverage & revision inspection / backup-restore verification；
- ⏭️ 之后：persistent Cortex HTTP client lifecycle，再完成 deployment release gate。

当前状态与 roadmap 见 [`docs/optimization_review_zh.md`](docs/optimization_review_zh.md)。Phase A–E 的旧 acceptance 文档保留为**历史验收证据**，不作为当前产品说明。

## CI、版本与安全

每个 PR、每次 push 到 `master` 的强制 CI 链路为：

```text
Python compile
→ Ruff
→ pytest
→ Node unit / architecture tests
→ Playwright Chromium smoke
→ secret scan
→ git diff --check
```

不要在长期文档里维护固定测试数量；以最新 green workflow 为准。真实 licensed `data/raw/` 不存在于 GitHub runner，因此生产持久卷上的 raw/history audit 与 restore drill 仍属于 deployment/operations Gate，不能用空 CI runner 伪造 green evidence。

应用/package 当前版本为 **0.4.0**，唯一版本常量在 `app/version.py`。

安全边界：

- 凭证、token、Authorization header 不落盘、不进日志、不回显；
- licensed raw/normalized/history data 不进入 Git、Docker image 或公开 artifact；
- `/health/ready` 不为健康检查获取 token；
- 当前 GitHub repository 为 public，因此正式团队交付前仍必须完成 repository-private release gate；
- Cortex Playground 只面向当前小型可信内部环境；共享范围扩大时必须重新评估 enable flag / route auth / proxy ACL。

部署与数据治理分别见 [`docs/operations_runbook_zh.md`](docs/operations_runbook_zh.md) 和 [`docs/data_retention_policy_zh.md`](docs/data_retention_policy_zh.md)。