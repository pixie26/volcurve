# 前端 Correctness Test Boundary

当前修订：2026-08-08

本文件记录 Time Series 前端的测试职责，避免再次用大量源码字符串断言替代真实执行测试。

## 测试分层

1. `tests/js/frontend_statistics.test.mjs`
   - 使用 Node 内置 `node:test`；
   - 直接执行 `compare-builder.js` 当前的纯统计/derived arithmetic 函数；
   - 90 个观测、一个缺口的主样本与独立 Python oracle 逐字段核对；
   - 额外覆盖 null/gap、乱序日期、constant/small sample、divide-by-zero 等边界。

2. `tests/browser/time_series.spec.mjs`
   - 使用 Playwright + Chromium；
   - 真实加载 FastAPI 页面并执行浏览器 JavaScript；
   - 页面初始化时不得产生 `pageerror` 或 console error；
   - 真实执行新增 indicator、Plotly render、statistics render；
   - 真实执行 Bulk Fixed maturity，并核对发送的是精确 fixed request。

3. `tests/integration/test_phase_d_web.py`
   - 只保留少量静态 contract：offline assets、required controls、capability/disclosure boundary、wire defaults、关键产品语义；
   - 不再通过函数名/源码位置来假装验证行为。

## CI

GitHub Actions 对每个 PR 与 master push 运行：Python compile/Ruff/pytest、Node unit tests、Playwright Chromium smoke、secret scan 与 `git diff --check`。

真实 licensed `data/raw/` 不存在于 GitHub runner，因此生产持久卷上的 `audit_raw_hashes.py` 仍属于 deployment/operations Gate；其算法正确性由 pytest/synthetic fixture 覆盖，不能在空 CI runner 上制造“raw audit green”的错觉。

## 已知小项

`sessionsSinceMax/Min` 当前仍使用第一次出现的极值；更自然的产品语义应为最近一次出现。该项已在 Node suite 中显式标为 TODO，待纯逻辑正式抽离 `compare-builder.js` 时一起修正并冻结 tie policy。

`positiveShare` 对大多数始终为正的 level series 信息量很低，当前保持默认隐藏；对 signed/derived series 仍可能有意义，因此暂不删除。
