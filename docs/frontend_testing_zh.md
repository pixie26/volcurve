# 前端 Correctness Test Boundary

当前修订：2026-08-09（7.5 closed）

本文件记录 Time Series 前端的测试与代码边界，避免再次用大量源码字符串断言替代真实执行测试，也避免 `compare-builder.js` 重新长回单体文件。

## 7.5 最终代码边界

- `app/web/compare-core.js`
  - 唯一的 Time Series pure-core implementation；
  - 负责 statistics、derived arithmetic、`coordinateSignature`、`boardSignature`、stable serialization；
  - 不依赖 DOM / fetch / localStorage / mutable UI state；
  - Browser production 与 Node tests 直接执行同一份文件。
- `app/web/compare-workspace.js`
  - workspace / board / bulk state 与 localStorage persistence。
- `app/web/compare-request.js`
  - exact-coordinate request serialization、fetch lifecycle、series resolution。
- `app/web/compare-render.js`
  - DOM / Plotly / details / statistics table rendering。
- `app/web/compare-builder.js`
  - 只保留模块 bootstrap 与 orchestration/controller。

`compare-builder.js` 不再保存 statistics / derived arithmetic 的第二份实现。

## 测试分层

1. `tests/js/frontend_statistics.test.mjs`
   - 使用 Node 内置 `node:test`；
   - 直接 `require` production `compare-core.js`，不存在源码 extraction / VM seam；
   - 90 个观测、一个缺口的主样本与独立 Python oracle 逐字段核对；
   - 覆盖 null/non-finite、乱序日期、constant/small-N、1D/5D/20D changes、derived arithmetic、common-date semantics、divide-by-zero、signature semantics；
   - repeated max/min tie policy 固定为：`maxDate/minDate` 与 `sessionsSinceMax/Min` 使用**最近一次**达到该极值的 observation。

2. `tests/js/frontend_architecture.test.mjs`
   - 对全部 split browser modules 执行 `node --check`；
   - 强制 `compare-builder.js` 保持 thin controller；
   - 防止 `summarizeSeries` / `applyOperator` / signatures 再次复制到其他模块；
   - 保护 workspace / request / render 的职责边界。

3. `tests/browser/time_series.spec.mjs`
   - 使用 Playwright + Chromium；
   - 真实加载 FastAPI 页面并执行浏览器 JavaScript；
   - 页面初始化不得产生 `pageerror` 或 unexpected console error；
   - 真实执行新增 indicator、request、Plotly render、statistics render；
   - 真实执行 Bulk Fixed maturity，并核对发送的是精确 Fixed coordinate，而不是最近期限替代。

4. `tests/integration/test_phase_d_web.py`
   - 只保留静态 contract：offline assets、required controls、capability/disclosure boundary、wire defaults、关键产品语义；
   - split JS 文件本身是否被 FastAPI serve 也属于 asset contract；
   - JS 算得对不对、按钮是否可点击、点击后是否报错、request 是否真实发送正确，都由 Node / Playwright 承担。

## Statistics ownership（7.5F）

Time Series 用户可见 range statistics，以及 A-B / A+B / A×B / A÷B 等 browser-derived series 的统计，以 `compare-core.js` 为 canonical implementation。

`app/analytics/statistics.py` **保留**：consumer audit 确认它仍被 `AnalyticsEngine.run_compare` 使用，并继续支撑后端公开 `CompareSummary` contract。因此这里不是为了“只留一种语言”而删除真实 backend consumer；前后端职责已经明确分开。

## CI

GitHub Actions 对每个 PR 与 master push 强制运行：

Python compile → Ruff → pytest → Node unit tests → Playwright Chromium smoke → secret scan → `git diff --check`。

真实 licensed `data/raw/` 不存在于 GitHub runner，因此生产持久卷上的 `audit_raw_hashes.py` 仍属于 deployment/operations Gate；其算法正确性由 pytest/synthetic fixture 覆盖，不能在空 CI runner 上制造“raw audit green”的错觉。

## 7.5 closure

7.5A–G 已关闭。下一阶段可以回到 Historical Archive Operations / operational hardening；前端再做结构调整时必须先保持 Node + Playwright + Python API tests + CI 全绿，再进行小步重构。

`positiveShare` 对大多数始终为正的 level series 信息量仍较低，当前保持默认隐藏；对 signed/derived series 仍可能有意义，因此暂不删除。
