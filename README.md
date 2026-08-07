# Cortex Vol Analytics

内部波动率分析 Web 工具,数据源为 BNP Paribas Cortex DataHub API。
拉取隐含波动率(IV)与已实现波动率(RV),做 IV−RV、分位数、z-score、相关性等对比分析,提供 REST API 与离线前端页面。

## 技术栈

- **Python ≥ 3.11**(见 `pyproject.toml`)
- **FastAPI + Uvicorn** — REST API
- **httpx** — Cortex DataHub 客户端(重试 / 429 退避 / 401 重认证 / 持久缓存)
- **pandas + PyArrow + DuckDB** — 标准化存储与查询
- **Plotly**(离线 vendor bundle,不走 CDN)
- **pytest** — 单元 + 契约测试

## 目录结构

```
app/
  clients/cortex/   # BNP 认证、客户端、解析、错误、模型
  domain/           # 归一化请求/观测/标的模型(BNP 线格式仅在此转换)
  storage/          # raw 原始落盘 + normalized parquet + DuckDB 目录 + 缓存
  analytics/        # RV、对齐预热、质量标记、统计(分位/z-score/相关性)
  security/         # 日志脱敏
  web/              # Phase D 单页 Web、样式与离线 Plotly bundle
  config.py
scripts/            # 各 Gate 探针(auth/instruments/qqq/cache)与 fixture 生成
tests/fixtures/     # 脱敏后的离线响应样本
schemas/            # Cortex OpenAPI 规范
docs/bnp/           # 离线 BNP 官方文档与 SDK 源码(不联网)
data/               # raw + normalized + catalog.duckdb(gitignored,可从 raw 重建)
```

## 配置

复制 `.env.example` 为 `.env`,填入凭证:

```
BNP_CLIENT_ID=
BNP_CLIENT_SECRET=
BNP_TOKEN_URL=https://api.cib.bnpparibas.com/oauth2/v1/token
BNP_BASE_URL=https://api.cib.bnpparibas.com/gm-cortex-datahub
CORTEX_MODE=live        # live | fixture
```

`.env` 与 `data/` 均在 `.gitignore` 中;raw API 响应可能含授权行情数据,**绝不入库**。
凭据不落盘、不进日志,token 内存缓存并提前 60s 刷新。

## 运行模式

- `CORTEX_MODE=live` — 真实调用 Cortex API
- `CORTEX_MODE=fixture` — 离线模式,从 `tests/fixtures/` 读取脱敏样本,无需凭证

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
`vol/compare`、`vol/surface`、`vol/compare.csv` 与 health；页面只展示 capability registry 中
`enabled=true` 的请求模式。

在 `Fixed/Listed · 绝对 strike` 模式中，可按 instrument 和 observation date 点击“加载可用坐标”。
页面通过单日、无 strike/expiry 边界的 `fixed maturity + fixed strike` Surface 请求读取 BNP 当天
实际返回的 listed expiries；选择 expiry 后，只把该 expiry 下 effective IV 有效的 strikes 放入下拉。
无效坐标数量和 flags 仍会显示，任何 expiry/strike 都必须由用户明确选择并应用，不做最近值替代。

## Gate 探针(逐阶段验收)

| 脚本 | 阶段 | 作用 |
|------|------|------|
| `scripts/auth_probe.py` | Gate 0 | 认证 / 连通 / entitlement(403 即停) |
| `scripts/instruments_probe.py` | Phase 1 | 拉取标的清单,实况解析 QQQ 的 BNP code |
| `scripts/qqq_probe.py` | Phase 1 | IV 探针,确定 matrix 方向与 IV 单位,产出 `qqq_probe.csv` |
| `scripts/make_fixtures.py` | Phase 1 | 由 live 响应生成脱敏 fixture |
| `scripts/cache_probe.py` | Gate 2 | 同请求跑两次(live→cache),验证标准化结果一致 |
| `scripts/validate_rv.py` | Phase E | live 10 日期 IV 核对与独立 RV 复算 |
| `scripts/phase_c_api_probe.py` | Phase E | live fixed/delta/listed 与 API/CSV 一致性 |
| `scripts/audit_raw_hashes.py` | Phase E | 对所有 COMPLETED raw payload 重算 hash |
| `scripts/secret_scan.py` | Phase E | 扫描候选文件、完整可达 Git 历史及当前配置值 |

## 计算口径(确认)

- **RV**:收盘对数收益 `r_t = log(S_t/S_{t-1})`,样本标准差 ddof=1 去均值(=Excel `STDEV.S`),`√252` 年化
- **预热**:拉取起始日 = 用户起始日 − `ceil(窗口×7/5)` − 10 日历日;显示区间严格不变;尾部留空不补零
- **IV 单位 / matrix 方向**:由 Phase 1 探针确认,见数据契约

## 数据恢复

`data/raw/` 为权威源;`data/normalized/` 与 `data/catalog.duckdb` 可从 raw 重建。
raw 响应 gzip 压缩,以请求哈希命名;normalized 落 parquet。

## 当前状态（2026-08-07 优化后）

- ✅ Phase 0 — 项目骨架、离线文档、认证管理、Gate 0
- ✅ Phase 1 — instrument + QQQ IV 探针,方向/单位确认
- ✅ Phase 2 — Cortex 客户端(重试/429/401/缓存)、raw+DuckDB 存储、fixture 模式,Gate 2 PASS
- ✅ Phase 3 — RV/IV−RV/分位/z-score/相关性计算 + 独立复算
- ✅ Phase A 正确性加固 — invalid IV、duplicate、完整 cache 状态、forward 自动追加、质量响应契约、UTC、latest comparable、return-outlier 语义（Gate A PASS）
- ✅ Phase B — request models、独立 serializer、多模式 parser、fixtures、disclosures 与七组真实 API probes 全部通过（Gate B PASS）
- ✅ Phase C / Phase 4 — FastAPI instruments、compare、surface、CSV、统一 errors、activity events 与 live API probes 全部通过（Gate C PASS）
- ✅ Phase D / Phase 5 — 动态 Web、Compare/Surface、listed 合约坐标发现、smile/term structure、表格/CSV、methodology、quality/activity/disclosures（技术 Gate 通过，UX 待修订）
- ✅ Phase E / Phase 6–7 — 独立数值核对、完整 secret/dependency scan、single-worker 部署与运维说明（Gate E PASS；Docker build 待部署主机复验）
- 🚧 Phase F1 — Compare 支持最多 5 个上下同步坐标、每 indicator 独立标的、同日 hover、矩形 zoom 与跨页面重开恢复；逐 indicator 数据、方法、质量、activity、disclosures 与 CSV 已接回；等待用户 UI 验收
- 🚧 Phase F2 — 跨坐标 hover 读数条与同步竖向指示线（hover 任一坐标即读出该日期在全部坐标上的数值）、查询栏改为「日期范围 → underlying + 坐标 → indicator」单一入口、saved indicator 之间的 ＋ − × ÷ 组合指标、显示中指标的区间统计表；等待用户 UI 验收
- 🚧 Phase F3 — saved indicator 支持就地编辑与复制；board（具名可重载页面）保存 indicator 配置 + 坐标布局 + 日期范围并在载入时重新取数；区间统计扩展到 24 项（变化/IQR/z-score/极值日期/最大单日涨跌/偏度/峰度/自相关等），列的显示与顺序可自定义并保存；等待用户 UI 验收

代码级审阅、原计划修订意见和 Gate 状态见
[`docs/optimization_review_zh.md`](docs/optimization_review_zh.md)。
Phase A 的逐项验收证据见
[`docs/phase_a_acceptance_zh.md`](docs/phase_a_acceptance_zh.md)。
Phase B 的完整验收与 live probe 证据见
[`docs/phase_b_acceptance_zh.md`](docs/phase_b_acceptance_zh.md)。
Phase C 的 REST API、fixture/live Gate 与用户检查项见
[`docs/phase_c_acceptance_zh.md`](docs/phase_c_acceptance_zh.md)。
Phase D 的 Web 功能、浏览器验收证据与用户检查项见
[`docs/phase_d_acceptance_zh.md`](docs/phase_d_acceptance_zh.md)。
Phase E 的逐项结果与环境边界见
[`docs/validation_report.md`](docs/validation_report.md)，部署步骤见
[`docs/operations_runbook_zh.md`](docs/operations_runbook_zh.md)，licensed raw data 边界见
[`docs/data_retention_policy_zh.md`](docs/data_retention_policy_zh.md)。
Compare indicator builder 的产品语义、BNP 字段解释和用户检查项见
[`docs/phase_f_compare_indicator_builder_zh.md`](docs/phase_f_compare_indicator_builder_zh.md)。

## Phase E 最终交付（已完成）

用户已允许 Phase D 的 UX 修订不阻塞最后一个阶段 Phase E。本阶段已交付：

- 独立 IV/RV 与 fixed/delta/listed 抽样核对结果；
- Web 页面、REST API 与 CSV 的一致性验证入口；
- secret scan、dependency audit 与 raw hash 验证命令；
- Docker、single-worker 内网部署方式和健康检查；
- licensed raw data 保留边界、故障处理及日常运维入口；
- 最终 validation report、operations runbook 与 raw retention policy。

Gate E 已通过。当前主机没有 Docker CLI，因此 Dockerfile 通过静态契约、隔离 production install、wheel build 与真实 Uvicorn smoke 验证；实际 image build 和持久卷 health 仍须在部署主机完成，详见 validation report。

## 安全

- 凭证、token、Authorization 头不落盘、不进日志、不回显
- `app/security/redaction.py` 负责日志脱敏
- raw 行情数据不入 git
- `/health/ready` 的 Cortex 连通性用缓存结果,不触发 token 获取
