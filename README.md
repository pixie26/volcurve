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

## Gate 探针(逐阶段验收)

| 脚本 | 阶段 | 作用 |
|------|------|------|
| `scripts/auth_probe.py` | Gate 0 | 认证 / 连通 / entitlement(403 即停) |
| `scripts/instruments_probe.py` | Phase 1 | 拉取标的清单,实况解析 QQQ 的 BNP code |
| `scripts/qqq_probe.py` | Phase 1 | IV 探针,确定 matrix 方向与 IV 单位,产出 `qqq_probe.csv` |
| `scripts/make_fixtures.py` | Phase 1 | 由 live 响应生成脱敏 fixture |
| `scripts/cache_probe.py` | Gate 2 | 同请求跑两次(live→cache),验证标准化结果一致 |

## 计算口径(确认)

- **RV**:收盘对数收益 `r_t = log(S_t/S_{t-1})`,样本标准差 ddof=1 去均值(=Excel `STDEV.S`),`√252` 年化
- **预热**:拉取起始日 = 用户起始日 − `ceil(窗口×7/5)` − 10 日历日;显示区间严格不变;尾部留空不补零
- **IV 单位 / matrix 方向**:由 Phase 1 探针确认,见数据契约

## 数据恢复

`data/raw/` 为权威源;`data/normalized/` 与 `data/catalog.duckdb` 可从 raw 重建。
raw 响应 gzip 压缩,以请求哈希命名;normalized 落 parquet。

## 当前状态（2026-08-06 优化后）

- ✅ Phase 0 — 项目骨架、离线文档、认证管理、Gate 0
- ✅ Phase 1 — instrument + QQQ IV 探针,方向/单位确认
- ✅ Phase 2 — Cortex 客户端(重试/429/401/缓存)、raw+DuckDB 存储、fixture 模式,Gate 2 PASS
- ✅ Phase 3 — RV/IV−RV/分位/z-score/相关性计算 + 独立复算
- ✅ Phase A 正确性加固 — invalid IV、duplicate、完整 cache 状态、forward 自动追加、质量响应契约、UTC、latest comparable、return-outlier 语义（Gate A PASS）
- ✅ Phase B — request models、独立 serializer、多模式 parser、fixtures、disclosures 与七组真实 API probes 全部通过（Gate B PASS）
- ✅ Phase C / Phase 4 — FastAPI instruments、compare、surface、CSV、统一 errors、activity events 与 live API probes 全部通过（Gate C PASS）
- ✅ Phase D / Phase 5 — 动态 Web、Compare/Surface、smile/term structure、表格/CSV、methodology、quality/activity/disclosures（Gate D PASS，等待用户检查）
- ⬜ Phase E / Phase 6–7 — 独立数值核对、完整 secret/dependency scan、部署与运维说明

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

## Phase E 最终交付

Phase D 经用户确认后进入最后一个阶段 Phase E。该阶段除代码和验证外，也会同步更新本 README，最终至少覆盖：

- 独立 IV/RV 与 fixed/delta/listed 抽样核对结果；
- Web 页面、REST API 与 CSV 的一致性验证入口；
- secret scan、dependency audit 与 raw hash 验证命令；
- Docker、single-worker 内网部署方式和健康检查；
- licensed raw data 保留边界、故障处理及日常运维入口；
- 最终 `validation_report.md` 与 operations runbook 链接。

在 Phase E Gate 通过前，上述内容属于待交付项，不应将当前版本视为已完成生产部署验收。

## 安全

- 凭证、token、Authorization 头不落盘、不进日志、不回显
- `app/security/redaction.py` 负责日志脱敏
- raw 行情数据不入 git
- `/health/ready` 的 Cortex 连通性用缓存结果,不触发 token 获取
