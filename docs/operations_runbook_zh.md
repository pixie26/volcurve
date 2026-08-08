# VolCurve 部署与运维 Runbook

初版日期：2026-08-07  
当前修订：2026-08-08

## 部署约束

- 仅部署在获准访问 BNP Cortex 的内网/受控环境。
- GitHub 仓库当前为 public；安全边界**不得依赖 repository visibility**。`.env`、token、licensed raw response、内部部署 secret 或未脱敏行情样本不得提交 Git。若未来需要把上述内部材料纳入仓库，应先把仓库改为 private/restricted。
- Uvicorn 固定 `--workers 1`。当前进程内 singleton client、连接状态 beacon、本地 DuckDB/cache 与 process-wide upstream limiter 都按单 worker 设计。
- `.env`、token、`data/` 不得复制进 image。凭据由运行环境或 secret manager 注入。
- `/app/data` 必须挂载持久卷；否则容器重建会丢失 raw 权威源与 catalog。
- 当前真实 Cortex HTTP attempts 进程内最多 4 个同时执行；不要通过增加 worker 绕过该限制。

## 本机启动

```powershell
python -m pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

浏览器访问 `http://127.0.0.1:8000/`。内网反向代理应终止 TLS，并限制来源网络；应用本身目前不提供多用户登录。

## Docker

当前应用/package 版本唯一来源为 `app/version.py`，当前版本 `0.4.0`。

```powershell
docker build -t volcurve:0.4.0 .
docker run --rm -p 127.0.0.1:8000:8000 `
  --env-file .env `
  --mount type=bind,source=D:\secure\volcurve-data,target=/app/data `
  volcurve:0.4.0
```

不要把服务直接绑定到公网接口。若由反向代理提供内网访问，只向代理所在网络开放容器端口。

## Cortex Playground 部署边界与留痕

当前 Raw API Playground 在 live mode 下可用，并直接复用服务器的 Cortex authentication / timeout / retry / proxy / TLS 能力。它故意绕过应用 cache、domain normalization、analytics 与 normalized storage，用于快速验证原始 Cortex request/response。

2026-08-08 决策：**暂不增加 `CORTEX_PLAYGROUND_ENABLED` deployment flag**。原因是当前使用者为小型、可信内部团队，服务也不计划直接暴露公网；额外 flag 的维护收益暂时有限。

这不是永久安全结论。出现以下任一情况时，应重新评估独立 enable flag、route-level auth 或更严格的反向代理 ACL：

- 团队人数明显扩大，或加入不应共享同一 Cortex entitlement 的用户；
- 服务从个人/小团队工具变成共享 desk service；
- 网络访问范围扩大到更广内网、跨区域或公网入口；
- 引入多用户登录、不同 entitlement 或审计隔离要求；
- Playground 扩展到更多 upstream endpoint 或具备更高查询成本/敏感度。

在重新评估前，Playground 不应被当成公开 API；其安全边界依赖当前受控部署环境和可信用户范围。

## 健康检查

- `GET /health/live`：进程存活，不访问 BNP；
- `GET /health/ready`：检查本地存储并读取最近连接 beacon，不为健康检查获取 token；
- readiness 中 `connected=null` 表示启动后还没有实际 Cortex 请求，不等于连接失败。

## 并发与重试

- 相同 request hash：single-flight 合并为一个 upstream call；
- 不同真实 HTTP attempts：process-wide semaphore 上限 4；
- 429/5xx retry：每次 attempt 结束后先释放 slot，再 backoff，下一次 attempt 重新排队；
- cache hit 与 fixture mode 不占 upstream slot；
- 当前 `--workers 1` 下，进程级上限就是服务级上限。若未来改多 worker，需要先重做跨进程并发与本地 DuckDB/cache 一致性设计。

## 发布前 Gate

GitHub Actions 是默认 CI Gate，每个 PR 和每次 push 到 `master` 自动执行 install、compile、Ruff 与 pytest。本机发布前仍建议运行：

```powershell
python -m pytest -q
python -m ruff check .
python -m compileall -q app scripts tests
python scripts/secret_scan.py
python scripts/audit_raw_hashes.py
python -m pip check
python -m pip_audit -r requirements.prod.lock --strict
git diff --check
```

Live 数值 Gate 使用 `scripts/validate_rv.py` 和 `scripts/phase_c_api_probe.py`；两者报告写入 gitignored `data/normalized/`，不得提交行情值。

当前开发主机没有 Docker CLI；Phase E 已完成 production lock 的隔离安装、wheel build 和 single-worker Uvicorn HTTP 200 smoke，但实际 image build 必须在部署主机按本节命令复验，不能用上述替代证据冒充容器验收。

## 常见故障

| 现象 | 检查 | 操作 |
|---|---|---|
| 401 / authentication failed | client ID/secret、token URL、主机时间 | 修正 secret 注入后重启；不要把 token 打到日志 |
| 403 / entitlement | BNP entitlement | 停止重试并联系数据负责人/BNP，不绕过权限 |
| 429 | activity event / Retry-After / 并发 | 等待内置 bounded backoff；不要并发扩 worker |
| schema changed | API version、raw hash audit | 保留 raw，停止使用受影响结果，先更新 parser/fixture/test |
| raw hash mismatch | `audit_raw_hashes.py` | 隔离受影响 cache，禁止把它当 cache hit；从上游受控刷新 |
| forward RV 尾部为空 | available-through、activity | 这是未实现未来窗口时的预期 null；不得补零或取邻近窗口 |
| DuckDB locked | 是否启动了多个 worker/进程 | 停止额外实例，确认只有一个写进程后再启动 |

## 备份与恢复

按 [licensed raw data 保留策略](data_retention_policy_zh.md) 管理整个 `data/` 持久卷。恢复优先级为 raw → catalog/normalized 重建；恢复后先运行 raw hash audit，再开放查询。
