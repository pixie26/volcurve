# Phase E 验证报告

日期：2026-08-07  
范围：VolCurve Phase E（数值、核心模式、页面/API/CSV、安全、完整性、部署）  
结论：**Gate E 通过；Docker image build 需在装有 Docker 的部署主机再执行一次。**

## Gate E 结论

| Gate | 结果 | 证据摘要 |
|---|---|---|
| 核心模式样本 | 通过 | live K/S、delta、fixed、listed compare/surface 均返回 200；结构与活动事件检查通过 |
| 10 日期 IV | 通过 | QQQ 3M K/F=100%，从 261 个展示日中分布抽取 10 日；raw matrix 与 engine mismatch 为 0 |
| RV 独立复算 | 通过 | 63-session trailing RV 用 stdlib `log`、`stdev`、`sqrt(252)` 独立复算；261 行、容差 `1e-10`、mismatch 为 0 |
| Page/API/CSV | 通过 | live Compare JSON 与后端 CSV 8 行逐值一致；页面直接渲染同一 API series，不在浏览器重算；Phase D 浏览器 fixture runtime 无 console/page error |
| Raw hash | 通过 | 数值 cache 1/1、API cache 13/13 完整；missing、unreadable、mismatch 均为 0 |
| Secret scan | 通过 | 当前候选文件、全部可达 Git 历史，以及 `.env` 当前 client ID/secret 精确值均检查；值不回显 |
| Dependency audit | 通过 | strict `pip-audit` 最终 0 known vulnerabilities |
| Private repository | 通过 | authenticated GitHub metadata：`pixie26/volcurve` 为 `PRIVATE` |
| 内网部署说明 | 通过 | non-root image、外置 data volume、single worker、health、备份/恢复与故障处理已写入 runbook |
| Raw retention policy | 通过 | licensed raw/normalized/catalog 的访问、复制、备份、删除和合同责任边界已明确 |

## 数值与 live API 证据

`scripts/validate_rv.py` 在隔离的 `data/phase_e_runtime/` 中强制 live refresh：

- 请求范围：2025-04-29 至 2026-08-05；展示范围：2025-08-06 至 2026-08-05；
- 332 个上游 observation，261 个展示行；
- IV raw/effective 坐标核对 mismatch = 0；
- 10 个分布抽样日期均完成核对；
- trailing RV mismatch = 0；
- 无 RV zero-fill；无 warm-up 时前 63 session 为 null；forward 最后 63 session 为 null。

`scripts/phase_c_api_probe.py` 使用独立 `data/phase_e_api_runtime/`，强制 live refresh，并通过：

- instruments；
- compare K/S；
- compare delta；
- fixed surface 与 fixed compare；
- listed surface 与 listed compare；
- Compare JSON/CSV 行数及 IV、RV 数值一致性。

报告只保存日期、计数、状态与 mismatch 数；实际行情值仅写入 gitignored 私有验证 CSV/raw cache。

## 安全与依赖

首轮 dependency audit 在旧锁中发现 3 个包的 10 条漏洞记录。已升级：

- `idna 3.7 → 3.15`；
- `python-dotenv 1.1.0 → 1.2.2`；
- `starlette 1.0.0 → 1.3.1`。

补齐 `annotated-doc==0.0.5` 后，生产锁在全新隔离 virtual environment 中安装成功，wheel 构建成功，`pip check` 通过，最终 strict audit 为 0 known vulnerabilities。

Secret scanner 不扫描一整段无法定位文件的 patch，而是逐个检查所有可达 commit 的 Git blob；当前候选文件也包含尚未提交但未被 ignore 的文件。scanner 会从本机 `.env` 读取当前配置值做精确匹配，但不会打印命中值。

## 测试与运行时

在按 `requirements.prod.lock` 新建的隔离环境中：

```text
pytest: 96 passed
ruff check: PASS
ruff format --check: PASS
compileall: PASS
pip check: PASS
uvicorn --workers 1 fixture smoke: HTTP 200
fixture readiness: HTTP 200, status=ready, OpenAPI schema present
```

测试环境出现一条 Starlette 关于未来 TestClient/httpx2 迁移的 deprecation warning；不影响生产运行或本 Gate，后续测试工具升级时处理。

## Docker 验证边界

当前主机没有 Docker CLI，因此没有声称实际完成 `docker build`。已完成的替代证据是：

- Dockerfile 契约测试：non-root user、`/app/data` volume、`--workers 1`；
- `.dockerignore` 排除 `.env`、`data/`、tests、docs 和本地缓存；
- 与 image 相同的 production lock 全新安装、wheel build、应用 import 和真实 Uvicorn health smoke 均通过。

部署主机上线前仍必须执行 runbook 中的 `docker build`、容器 health 和持久卷检查。这个限制不改变代码与文档交付完成状态，但属于部署环境的最终 operational acceptance。

## 可重跑命令

```powershell
python scripts/validate_rv.py
python scripts/phase_c_api_probe.py
python scripts/audit_raw_hashes.py
python scripts/secret_scan.py
python -m pip_audit -r requirements.prod.lock --strict
python -m pytest -q
```

完整部署命令、故障处置和备份恢复见 [operations runbook](operations_runbook_zh.md)；数据边界见 [licensed raw data 保留策略](data_retention_policy_zh.md)。
