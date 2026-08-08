# Cortex Vol Analytics

内部波动率分析 Web 工具，数据源为 BNP Paribas Cortex DataHub API。
拉取隐含波动率（IV）与已实现波动率（RV），做 IV−RV、分位数、z-score、相关性等对比分析，提供 REST API 与离线前端页面。

## 技术栈

- **Python ≥ 3.11**（见 `pyproject.toml`）
- **FastAPI + Uvicorn** — REST API
- **httpx** — Cortex DataHub 客户端（重试 / 429 退避 / 401 重认证 / 持久缓存）
- **pandas + PyArrow + DuckDB** — 标准化存储与查询
- **Plotly**（离线 vendor bundle，不走 CDN）
- **pytest + Ruff + GitHub Actions** — 单元/集成测试与 CI gate

## 目录结构

```text
app/
  clients/cortex/   # BNP 认证、客户端、解析、错误、模型
  domain/           # 归一化请求/观测/标的模型（BNP wire 格式在边界层转换）
  storage/          # raw 原始落盘 + normalized parquet + DuckDB 目录 + 缓存
  analytics/        # RV、对齐预热、质量标记、统计（分位/z-score/相关性）
  security/         # 日志脱敏
  web/              # 单页 Web、样式与离线 Plotly bundle
  config.py
  version.py        # 应用/package 版本唯一来源
scripts/            # 各 Gate 探针与 fixture 生成
tests/fixtures/     # 脱敏后的离线响应样本
schemas/            # Cortex OpenAPI 规范
docs/bnp/           # 离线 BNP 官方文档与 SDK 源码（不联网）
data/               # raw + normalized + catalog.duckdb（gitignored，可从 raw 重建）
```

## 配置

复制 `.env.example` 为 `.env`，填入凭证：

```text
BNP_CLIENT_ID=
BNP_CLIENT_SECRET=
BNP_TOKEN_URL=https://api.cib.bnpparibas.com/oauth2/v1/token
BNP_BASE_URL=https://api.cib.bnpparibas.com/gm-cortex-datahub
CORTEX_MODE=live        # live | fixture
```

`.env` 与 `data/` 均在 `.gitignore` 中；raw API 响应可能含授权行情数据，**绝不入库**。
凭据不落盘、不进日志，token 内存缓存并提前 60s 刷新。

## 运行模式

- `CORTEX_MODE=live` — 真实调用 Cortex API
- `CORTEX_MODE=fixture` — 离线模式，从 `tests/fixtures/` 读取脱敏样本，无需凭证

## 安装（PowerShell）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## 启动与验证

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
python -m pytest -q
```

浏览器打开 `http://127.0.0.1:8000/`。REST 入口包括 `capabilities`、`instruments`、
`vol/compare`、`vol/surface`、`vol/compare.csv`、Cortex Playground 与 health。
页面只展示 capability registry 中 `enabled=true` 的请求模式。

## 当前 Time Series 查询语义

主 indicator builder 只把两类 maturity 暴露给新建 indicator：

- **Sliding tenor**：例如 `1M`、`3M`，按每个 observation date 的剩余期限取点；
- **Listed expiry**：先选 observation date，页面自动读取当天实际 listed expiries，再由用户选择精确 expiry。

`fixed` maturity 仍保留在后端/OpenAPI/legacy 配置兼容层中，但不作为新主 UI 的普通入口；它不代表“任意日历日期都可插值”。

Strike 仍支持 percentage moneyness（K/F 或 K/S）、delta（仅合法组合）与 absolute strike。对于 **Listed expiry + absolute strike**，选择 expiry 后页面会自动读取该 observation date/expiry 下实际返回的 strikes，输入框同时支持键盘输入与下拉建议；不会静默映射到最近 strike 或最近 expiry。

`volatilityConvention` 与 `layout` 仍属于 wire/backend contract，默认使用受支持值并在 request/methodology 中披露，但不再占用主 indicator builder 的普通交互位置。

Time Series 工作台当前最多支持 **8 个**上下排列坐标；每个 indicator 独立保存 instrument、所属坐标和启用状态。跨图 hover 使用同一个精确 observation date，不前填、不插值、不选择最近交易日。

## Cortex 请求稳定性

- 相同 request hash 的并发请求由 single-flight 合并为一次 upstream call；
- 不同真实 Cortex HTTP attempts 共享进程内并发上限，当前最多 **4 个**同时执行；
- cache hit 与 fixture 不占 upstream slot；429/5xx 重试在 backoff 前释放 slot；
- 当前部署约束仍是 `--workers 1`，因此该上限等同于服务级最多 4 个同时 upstream attempts。

## Gate 探针（逐阶段验收）

| 脚本 | 阶段 | 作用 |
|---|---|---|
| `scripts/auth_probe.py` | Gate 0 | 认证 / 连通 / entitlement（403 即停） |
| `scripts/instruments_probe.py` | Phase 1 | 拉取标的清单，实况解析 QQQ 的 BNP code |
| `scripts/qqq_probe.py` | Phase 1 | IV 探针，确定 matrix 方向与 IV 单位，产出 `qqq_probe.csv` |
| `scripts/make_fixtures.py` | Phase 1 | 由 live 响应生成脱敏 fixture |
| `scripts/cache_probe.py` | Gate 2 | 同请求跑两次（live→cache），验证标准化结果一致 |
| `scripts/validate_rv.py` | Phase E | live 10 日期 IV 核对与独立 RV 复算 |
| `scripts/phase_c_api_probe.py` | Phase E | live fixed/delta/listed 与 API/CSV 一致性 |
| `scripts/audit_raw_hashes.py` | Phase E | 对所有 COMPLETED raw payload 重算 hash |
| `scripts/secret_scan.py` | Phase E | 扫描候选文件、完整可达 Git 历史及当前配置值 |

## 计算口径（确认）

- **RV**：收盘对数收益 `r_t = log(S_t/S_{t-1})`，样本标准差 ddof=1 去均值（=Excel `STDEV.S`），`√252` 年化
- **预热**：拉取起始日 = 用户起始日 − `ceil(窗口×7/5)` − 10 日历日；显示区间严格不变；尾部留空不补零
- **IV 单位 / matrix 方向**：由 Phase 1 探针确认，见数据契约

## 数据恢复

`data/raw/` 为权威源；`data/normalized/` 与 `data/catalog.duckdb` 可从 raw 重建。
raw 响应 gzip 压缩，以请求哈希命名；normalized 落 parquet。

## 当前状态（2026-08-08）

- ✅ Phase 0–E：认证、Cortex client、存储、IV/RV analytics、API、Web、数值与部署 Gate 已完成；
- ✅ Phase F Time Series：最多 8 个坐标、每 indicator 独立 instrument、同日 hover、同步 X zoom、indicator 组合、统计表、就地编辑/复制、board 持久化均已实现；
- ✅ Listed expiry / absolute strike：改为 observation date 驱动的直接 discovery，不再要求 Load/Apply；
- ✅ Error provenance：保留并安全展示上游 `suggestedAction`，同时区分 upstream/local fallback；
- ✅ Stabilization Step 1–4：修 stale tests、加入 GitHub Actions CI、统一 empty surface→`NO_DATA`、启用 Cortex upstream 并发上限；
- 🚧 后续 UX/工程 cleanup：Bulk Maturity 中 legacy Fixed date、raw-error logging 等继续单独处理。

代码级审阅、原计划修订意见和 Gate 状态见 [`docs/optimization_review_zh.md`](docs/optimization_review_zh.md)。
Phase A/B/C/D/E 的验收证据分别见对应 `docs/phase_*` 文档与 [`docs/validation_report.md`](docs/validation_report.md)。
部署步骤见 [`docs/operations_runbook_zh.md`](docs/operations_runbook_zh.md)，licensed raw data 边界见 [`docs/data_retention_policy_zh.md`](docs/data_retention_policy_zh.md)。
Time Series indicator builder 当前产品语义见 [`docs/phase_f_compare_indicator_builder_zh.md`](docs/phase_f_compare_indicator_builder_zh.md)。

## CI 与版本

每个 PR、每次 push 到 `master` 都由 `.github/workflows/ci.yml` 执行 install、compile、Ruff 与 pytest。
应用/package 当前版本为 **0.4.0**；唯一版本常量在 `app/version.py`，FastAPI metadata 与 setuptools package metadata 均从该值读取。Docker tag 也按同一版本执行，见 operations runbook。

## 安全

- 凭证、token、Authorization 头不落盘、不进日志、不回显；
- `app/security/redaction.py` 负责日志脱敏；
- raw 行情数据不入 git；
- `/health/ready` 的 Cortex 连通性用缓存结果，不触发 token 获取；
- Cortex Playground 当前为小型可信内部团队保留；未来若团队/访问范围扩大，需重新评估独立 enable flag 或额外访问控制，决策留痕见 operations runbook。
