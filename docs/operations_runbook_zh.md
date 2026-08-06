# VolCurve 部署与运维 Runbook

日期：2026-08-07

## 部署约束

- 仅部署在获准访问 BNP Cortex 的内网环境。
- 仓库必须保持 private；2026-08-07 已通过 GitHub authenticated metadata 确认为 `PRIVATE`。
- Uvicorn 固定 `--workers 1`。当前进程内 singleton client、连接状态 beacon 和本地 DuckDB/cache 不支持多 worker 的一致性假设。
- `.env`、token、`data/` 不得复制进 image。凭据由运行环境或 secret manager 注入。
- `/app/data` 必须挂载持久卷；否则容器重建会丢失 raw 权威源与 catalog。

## 本机启动

```powershell
python -m pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

浏览器访问 `http://127.0.0.1:8000/`。内网反向代理应终止 TLS，并限制来源网络和身份认证；应用本身目前不提供多用户登录。

## Docker

```powershell
docker build -t volcurve:0.1.0 .
docker run --rm -p 127.0.0.1:8000:8000 `
  --env-file .env `
  --mount type=bind,source=D:\secure\volcurve-data,target=/app/data `
  volcurve:0.1.0
```

不要把服务直接绑定到公网接口。若由反向代理提供内网访问，只向代理所在网络开放容器端口。

## 健康检查

- `GET /health/live`：进程存活，不访问 BNP。
- `GET /health/ready`：检查本地存储并读取最近连接 beacon，不为健康检查获取 token。
- readiness 中 `connected=null` 表示启动后还没有实际 Cortex 请求，不等于连接失败。

## 发布前 Gate

```powershell
python -m pytest -q
python -m ruff check app tests scripts
python -m ruff format --check app tests scripts
python -m compileall -q app scripts tests
python scripts/secret_scan.py
python scripts/audit_raw_hashes.py
python -m pip check
python -m pip_audit -r requirements.prod.lock --strict
git diff --check
```

Live 数值 Gate 使用 `scripts/validate_rv.py` 和 `scripts/phase_c_api_probe.py`；两者的报告写入 gitignored `data/normalized/`，不得提交行情值。

当前开发主机没有 Docker CLI；Phase E 已完成 production lock 的隔离安装、wheel build 和 single-worker Uvicorn HTTP 200 smoke，但实际 image build 必须在部署主机按本节命令复验，不能用上述替代证据冒充容器验收。

## 常见故障

| 现象 | 检查 | 操作 |
|---|---|---|
| 401 / authentication failed | client ID/secret、token URL、主机时间 | 修正 secret 注入后重启；不要把 token 打到日志 |
| 403 / entitlement | BNP entitlement | 停止重试并联系数据负责人/BNP，不绕过权限 |
| 429 | activity event / Retry-After | 等待内置 bounded backoff；不要并发扩 worker |
| schema changed | API version、raw hash audit | 保留 raw，停止使用受影响结果，先更新 parser/fixture/test |
| raw hash mismatch | `audit_raw_hashes.py` | 隔离受影响 cache，禁止把它当 cache hit；从上游受控刷新 |
| forward RV 尾部为空 | available-through、activity | 这是未实现未来窗口时的预期 null；不得补零或取邻近窗口 |
| DuckDB locked | 是否启动了多个 worker/进程 | 停止额外实例，确认只有一个写进程后再启动 |

## 备份与恢复

按 [licensed raw data 保留策略](data_retention_policy_zh.md)管理整个 `data/` 持久卷。恢复优先级为 raw → catalog/normalized 重建；恢复后先运行 raw hash audit，再开放查询。
