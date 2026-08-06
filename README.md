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

## 安装

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
```

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

## 当前状态

- ✅ Phase 0 — 项目骨架、离线文档、认证管理、Gate 0
- ✅ Phase 1 — instrument + QQQ IV 探针,方向/单位确认
- ✅ Phase 2 — Cortex 客户端(重试/429/401/缓存)、raw+DuckDB 存储、fixture 模式,Gate 2 PASS
- ⬜ Phase 3 — RV/IV−RV/分位/z-score/相关性计算 + 单测
- ⬜ Phase 4 — REST API(`/api/v1/instruments`、`/api/v1/vol/compare`、CSV、`/health/*`)
- ⬜ Phase 5 — 前端页面(默认 preset:QQQ/近1年/3M/K=F 100%/63 sessions/trailing)
- ⬜ Phase 6–7 — 校验报告、secret scan、启动说明

详见 `.zcode/plans/` 下的执行计划(本目录已 gitignore)。

## 安全

- 凭证、token、Authorization 头不落盘、不进日志、不回显
- `app/security/redaction.py` 负责日志脱敏
- raw 行情数据不入 git
- `/health/ready` 的 Cortex 连通性用缓存结果,不触发 token 获取
