# Phase A 正确性加固验收

验收日期：2026-08-06  
依据：`volcurve_comprehensive_optimization_plan.md` 的 Phase A / Gate A。

## 结论

Phase A 已完成，可以提交用户检查。本阶段只收口数据正确性与响应契约，没有提前开放 delta、fixed、listed，也没有把尚未完成的 REST/Web 功能标为可用。

## Gate A 逐项证据

| Gate | 结果 | 实施与验证 |
|---|---|---|
| 非正 IV 不进入任何统计 | 通过 | `raw_implied_vol` 保留原值，`implied_vol` 置空；spread、ratio、percentile、z-score、correlation 只使用有效值。回归测试同时检查 latest IV 与 comparable count。 |
| 前端所需异常信息已包含在 API response | 通过 | `CompareResponse` 含逐点 raw/effective IV 与 flags，并新增 `dataQuality`、warning banner、异常日期范围、flag counts、排除策略和 `activity`。本项验收的是 response contract；实际 compare 路由属于 Phase C。 |
| duplicate conflict 会 hard fail | 通过 | 完全相同记录去重并标记；同日内容冲突抛出 `AMBIGUOUS_DUPLICATE_DATE`，不会进入 analytics/cache completed。 |
| forward RV 使用 display end 后数据 | 通过 | `app/services/compare.py` 先使用初始 future buffer，再检查最后展示日开始的有效价格数；不足 `window + 1` 时追加，达到 availability cap 或 12 次安全上限后仍不足则保持 null。 |
| bad payload 不会成为 completed cache | 通过 | 成功状态依次为 `FETCHED → SCHEMA_VALIDATED → NORMALIZED → COMPLETED`；schema、parse、storage 失败写入对应失败状态。 |

## 本阶段新增的关键边界

- Forward 追加不会改变用户展示区间；追加数据只用于 RV 计算。
- 追加请求使用不重叠的后续日期区间，跨请求遇到同日冲突仍 hard fail。
- 可用数据不足时不伪造 RV；`forward_tail_complete=false`，analytics 尾部保持 null。
- 连续追加没有新增有效价格时指数扩大日历跨度，并设 12 次请求安全上限，避免历史空洞造成无界 API 请求。
- 异常响应不包含 token、Authorization、BNP raw body、stack trace 或本地路径。

## 本阶段不包含

- delta/fixed/listed 的完整坐标解析、fixture 与 live probe（Phase B）。
- `/api/v1/vol/compare` 等 REST 路由（Phase C）。
- Web warning banner、table、hover、activity panel 的视觉实现（Phase D）。

这些边界不是 Gate A 遗漏，而是按计划留给后续 Phase；capability registry 继续把未端到端验证的模式标为 disabled。

## 验证命令

```powershell
python -m pytest -q
python -m ruff check app tests scripts
python -m ruff format --check app tests scripts
python -m compileall -q app scripts tests
git diff --check
```

本次完整结果：`48 passed`；Ruff check/format、compileall、`git diff --check` 与 Markdown 本地链接检查全部通过。
