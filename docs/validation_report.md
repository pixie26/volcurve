# Phase E 验证报告（历史快照）

日期：2026-08-07  
范围：VolCurve Phase E（数值、核心模式、页面/API/CSV、安全、完整性、部署）  
当时结论：**Gate E 通过；Docker image build 需在装有 Docker 的部署主机再执行一次。**

> **适用边界（2026-08-08 补充）**：本文保存 2026-08-07 的验证证据，不是当前状态页。后续 Phase F 与 Stabilization Step 1–7 已继续改变 UI、cache/history 与测试规模。当前实现/roadmap 请看 [`optimization_review_zh.md`](optimization_review_zh.md)，当前产品契约请看 [`phase_f_compare_indicator_builder_zh.md`](phase_f_compare_indicator_builder_zh.md)。本文中的固定测试数量只代表当时那次 Gate。
>
> 另一个重要勘误：本文当时记录了 repository-private gate；**当前 2026-08-08 GitHub metadata 显示 repository 为 public**。因此 private-repository 不能再被视为当前已满足的 release condition，正式团队交付前仍需重新完成该 Gate。

## Gate E 当时结论

| Gate | 结果 | 证据摘要 |
|---|---|---|
| 核心模式样本 | 通过 | live K/S、delta、fixed、listed compare/surface 均返回 200；结构与活动事件检查通过 |
| 10 日期 IV | 通过 | QQQ 3M K/F=100%，从 261 个展示日中分布抽取 10 日；raw matrix 与 engine mismatch 为 0 |
| RV 独立复算 | 通过 | 63-session trailing RV 用 stdlib `log`、`stdev`、`sqrt(252)` 独立复算；261 行、容差 `1e-10`、mismatch 为 0 |
| Page/API/CSV | 通过 | live Compare JSON 与后端 CSV 8 行逐值一致；页面直接渲染同一 API series，不在浏览器重算；Phase D 浏览器 fixture runtime 无 console/page error |
| Raw hash | 通过 | 数值 cache 1/1、API cache 13/13 完整；missing、unreadable、mismatch 均为 0 |
| Secret scan | 通过 | 当时候选文件、可达 Git 历史与本机当前配置值均检查；值不回显 |
| Dependency audit | 通过 | strict `pip-audit` 当时最终 0 known vulnerabilities |
| Repository visibility | 历史证据，当前已失效 | 2026-08-07 验证时记录为 private；2026-08-08 当前 metadata 为 public，需重新完成 release gate |
| 内网部署说明 | 通过 | non-root image、外置 data volume、single worker、health、备份/恢复与故障处理已有 runbook |
| Data retention boundary | 通过但后续已扩展 | 当时覆盖 raw/normalized/catalog；Step 7 后已扩展到 `history.duckdb` 与 archive compaction |

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

补齐 `annotated-doc==0.0.5` 后，生产锁在全新隔离 virtual environment 中安装成功，wheel 构建成功，`pip check` 通过，当次 strict audit 为 0 known vulnerabilities。

Secret scanner 逐个检查可达 commit 的 Git blob；本机 `.env` 的当前配置值用于精确匹配但不会打印命中值。

## 当时测试与运行时证据

```text
pytest: 96 passed
ruff check: PASS
ruff format --check: PASS
compileall: PASS
pip check: PASS
uvicorn --workers 1 fixture smoke: HTTP 200
fixture readiness: HTTP 200, status=ready, OpenAPI schema present
```

这些数字是 2026-08-07 的验收快照。后续新增测试后不应更新本段；当前自动验证以最新 GitHub Actions green run 为准。

测试环境出现一条 Starlette TestClient/httpx2 migration deprecation warning；不影响当次 Gate。

## Docker 验证边界

当时主机没有 Docker CLI，因此没有声称实际完成 `docker build`。替代证据包括：

- Dockerfile contract test：non-root user、`/app/data` volume、`--workers 1`；
- `.dockerignore` 排除 `.env`、`data/`、tests、docs 和本地缓存；
- production lock 全新安装、wheel build、应用 import 和真实 Uvicorn health smoke。

**该缺口至今仍属于 release gate**：部署主机上线前必须执行真实 Docker build、container health 和 persistent-volume/restore 验证。

## 可重跑命令

```powershell
python scripts/validate_rv.py
python scripts/phase_c_api_probe.py
python scripts/audit_raw_hashes.py
python scripts/secret_scan.py
python -m pip_audit -r requirements.prod.lock --strict
python -m pytest -q
```

完整部署与恢复操作见 [`operations_runbook_zh.md`](operations_runbook_zh.md)；当前 licensed data 生命周期见 [`data_retention_policy_zh.md`](data_retention_policy_zh.md)。