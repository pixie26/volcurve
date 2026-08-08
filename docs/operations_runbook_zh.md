# VolCurve 部署与运维 Runbook

初版日期：2026-08-07  
当前修订：2026-08-09

## 部署约束

- 仅部署在获准访问 BNP Cortex 的内网/受控环境。
- GitHub repository 当前为 **public**；安全边界不得依赖 repository visibility。`.env`、token、licensed market data、内部 deployment secret 或未脱敏样本不得提交 Git。
- **正式团队交付 Gate：将 repository 切换为 private。** 这不替代 secret/raw-data 的独立安全边界。
- Uvicorn 固定 `--workers 1`。当前 singleton client、DuckDB/cache/history store 与 process-wide upstream limiter 都按单 worker 设计。
- `.env`、token、`data/` 不进入 image；凭据由运行环境或 secret manager 注入。
- `/app/data` 必须挂载持久卷；否则容器重建会丢失 request cache、catalog、historical points 与 revision provenance。
- Cortex 真实 HTTP attempts 进程内最多 4 个同时执行；不要通过增加 worker 绕过该限制。

## 本机启动

```powershell
python -m pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

浏览器访问 `http://127.0.0.1:8000/`。内网反向代理应终止 TLS 并限制来源网络；应用当前不提供多用户登录。

## Docker

当前应用/package 版本唯一来源为 `app/version.py`，当前版本 `0.4.0`。

```powershell
docker build -t volcurve:0.4.0 .
docker run --rm -p 127.0.0.1:8000:8000 `
  --env-file .env `
  --mount type=bind,source=D:\secure\volcurve-data,target=/app/data `
  volcurve:0.4.0
```

不要把服务直接绑定公网。若由反向代理提供内网访问，只向代理所在网络开放容器端口。

## 前端静态资产边界

Frontend 7.5 后 Time Series 由多个 production JS 模块组成：

```text
compare-core.js       # pure statistics / derived / signatures
compare-workspace.js  # workspace / board / bulk / persistence
compare-request.js    # request / fetch / series resolution
compare-render.js     # DOM / Plotly / detail / statistics render
compare-builder.js    # thin bootstrap/controller
```

部署时必须把这些文件与 `app.js`、`styles.css`、离线 Plotly bundle 作为同一版本静态资产发布。不要只复制旧的 `compare-builder.js` 覆盖生产目录；那会造成 HTML/controller 与 split modules 版本错配。

浏览器 boot smoke / Playwright 会检查 runtime exception；Python Web static tests 会检查关键 offline asset contract。详细前端边界见 [`frontend_testing_zh.md`](frontend_testing_zh.md)。

## 数据目录与 Step 7 lifecycle

`/app/data` 当前包含两类不同的数据资产：

1. **Request cache**：`raw/`、`normalized/`、`catalog.duckdb`。成功 request freshness 为滚动 8 小时；过期后下一次使用会尝试 Cortex refresh。
2. **Historical archive**：`history.duckdb`。保存精确 K/F%、K/S%、Delta 时间序列的 latest-known points、coverage metadata 与 revision deltas。

运维上必须注意：

- exact 与 covering cache 同时可用时，以更新的 `retrieved_at` 为准；
- newer successful request 完整覆盖 old request 时，旧 request files 可以被 compact；
- 因此 `raw/` 已不再是整个长期历史库的唯一可重建权威源；
- 不允许手工绕过 archive coverage / completed-state 检查直接删除数据文件；
- stale fallback 只允许用于 rate-limit、upstream unavailable、`NO_DATA` 等刷新失败且本地历史完整覆盖的场景；400/401/403/schema/local-contract error 必须直接暴露。

## Cortex Playground 部署边界

Raw API Playground 在 live mode 下直接复用服务器 Cortex authentication / timeout / retry / proxy / TLS，故意绕过应用 cache、domain normalization、analytics 与 normalized storage，用于验证原始 Cortex request/response。

当前决策：**暂不增加独立 deployment flag**，前提是服务只面向小型可信内部团队且不直接暴露公网。

出现以下任一情况时，必须重新评估 `CORTEX_PLAYGROUND_ENABLED`、route-level auth 或更严格的 proxy ACL：

- 服务变成共享 desk service；
- 用户数量或 entitlement boundary 明显扩大；
- 网络访问范围扩大；
- 引入多用户登录/审计隔离；
- Playground 扩展更多敏感或高成本 endpoint。

## 健康检查

- `GET /health/live`：进程存活，不访问 Cortex；
- `GET /health/ready`：检查本地存储并读取最近 connection beacon，不为 health check 获取 token；
- `connected=null` 表示启动后还没有实际 Cortex 请求，不等于连接失败。

## 并发、single-flight 与重试

- 相同 request hash：single-flight 合并为一个 upstream call；
- 不同真实 HTTP attempts：process-wide semaphore 上限 4；
- 429/5xx retry：每次 attempt 完成后先释放 slot，再 backoff；
- cache、historical archive 与 fixture path 不占 upstream slot；
- 当前 `--workers 1` 下进程级上限等同于服务级上限；未来若改多 worker，必须先重做跨进程并发和 DuckDB/cache 一致性设计。

当前 Cortex attempt 仍会为每个真实 HTTP request 创建并关闭一个 `httpx.Client`。这是已知性能/连接复用改进项，不是当前 correctness blocker；后续引入 persistent client 时必须保持上述 limiter、retry、auth 和 shutdown 语义不变。

## 自动 CI Gate

每个 PR 与每次 push 到 `master` 的 GitHub Actions 链路为：

```text
Python compile
→ Ruff
→ pytest
→ Node unit / architecture tests
→ Playwright Chromium smoke
→ secret scan
→ git diff --check
```

其中：

- pytest 负责 backend/domain/storage/API/integration；
- Node 直接执行 production `compare-core.js`，并保护 split-module architecture；
- Playwright 负责真实 Chromium boot、interaction、render、request serialization 与 runtime errors；
- GitHub runner 没有 licensed production `data/`，因此 raw/history audit、backup/restore drill 仍是独立 operations Gate。

CI green 是发布必要条件，但**不是 persistent-volume durability 的替代品**。

## 发布前 Gate

本机/部署主机在有完整开发依赖时建议执行：

```powershell
python -m compileall -q app scripts tests
python -m ruff check .
python -m pytest -q
npm install --no-package-lock --no-audit --no-fund
npm run test:js
npx playwright install chromium
npm run test:browser
python scripts/secret_scan.py
python scripts/audit_raw_hashes.py
python -m pip check
python -m pip_audit -r requirements.prod.lock --strict
git diff --check
```

如果部署主机不安装 Node/Playwright，则必须以对应 commit 的 GitHub Actions green workflow 作为前端 execution evidence，并在实际容器上至少完成页面 boot / static assets / representative Time Series interaction smoke。

Live 数值 Gate 使用 `scripts/validate_rv.py` 和 `scripts/phase_c_api_probe.py`；报告写入 gitignored data 目录，不得提交行情值。

当前开发主机未完成真实 Docker image build 证据；实际部署主机上线前仍必须完成 `docker build`、container health 与 persistent-volume smoke。

## 常见故障

| 现象 | 检查 | 操作 |
|---|---|---|
| 401 / authentication failed | client ID/secret、token URL、主机时间 | 修正 secret 注入后重启；不要记录 token |
| 403 / entitlement | BNP entitlement | 停止重试并联系数据负责人/BNP，不绕过权限 |
| 429 | Retry-After / 并发 | 等待内置 bounded backoff；不要增加 worker |
| schema changed | API version、raw response | 停止使用受影响结果，保留可用证据并先更新 parser/test |
| raw hash mismatch | `audit_raw_hashes.py` | 隔离受影响 request cache；受控重新拉取 |
| `STALE DATA` | source metadata、refresh reason | 可继续研究但明确视为 stale；上游恢复后重新 refresh |
| forward RV 尾部为空 | available-through | 未来有效 session 不足时为预期 null，不得补零 |
| DuckDB locked | 多 worker/多写进程 | 停止额外实例，恢复单写进程 |
| history 数据异常 | `history.duckdb`、coverage/revision | 在 Step 8 history-audit tooling 完成前停止 destructive cleanup，保留卷并人工检查 |
| 页面 boot 后 JS 报错 | 浏览器 console、static module versions、CI Playwright | 确认 split JS assets 来自同一 commit；不要只替换单个 builder 文件 |

## 备份与恢复

按 [`data_retention_policy_zh.md`](data_retention_policy_zh.md) 管理整个 `data/` 持久卷。

### 当前备份原则

- `history.duckdb` 必须与 request cache 一起备份；它已不是可随意删除并完全从 raw 重建的普通 cache；
- 备份不能只复制 `raw/`；
- 不在应用正在进行未知写事务时做未经验证的文件级热拷贝；生产备份方式需在 Step 8 operational hardening 中正式验证；
- revision provenance 和 historical coverage 的恢复完整性必须成为恢复验收的一部分。

### 当前恢复顺序

1. 保留恢复前现场，不覆盖原卷；
2. 恢复整个受控 `data/` snapshot；
3. 检查 `catalog.duckdb`、`history.duckdb` 可打开；
4. 对仍存在的 raw cache 执行 hash audit；
5. 以 fixture/local tests 验证 API 可启动；
6. 运行页面 boot / Time Series representative smoke，确认 split static modules 无 runtime error；
7. 受控 live refresh 一个已知 coordinate，确认 archive/cache 不产生异常 revision；
8. 再开放查询。

**当前缺口**：尚未有正式 `history_audit` / migration / backup-restore verification 工具。该项是 Step 8 的工程优先级。