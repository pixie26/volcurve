# Phase D Web MVP 验收说明

日期：2026-08-06

## 当前结论

Phase D 与 Gate D 已完成，现提交用户检查。FastAPI 现在同时托管 REST API 和离线单页 Web；页面不使用 CDN，四种请求模式与全部合法坐标均从 `/api/v1/capabilities` 读取。

本阶段没有改变 Phase C 的核心语义：Compare 只接受单一精确坐标，Surface 保留范围；缺失仍是缺失，绝不使用邻近 strike、expiry、maturity 或 RV window 替代。页面只把最近返回坐标作为参考文字，明确标注“不会替代请求”。

## 已实现

- 动态 Query Builder：`sliding_moneyness`、`sliding_delta`、`fixed_strike`、`listed_moneyness` 全部可发现；Compare 自动使用 exact low/high，Surface 显示范围字段。
- 默认 preset：`US_QQQ`、近一年、3M、K/F 100%、RV 63 sessions、trailing。
- Instrument 搜索：调用后端 catalogue；`hasMore=true` 时要求缩小关键词。
- 指标选择：IV、RV、spot、forward、IV−RV、IV/RV、percentile、z-score、correlation、smile、term structure。
- Compare 图：IV/RV/spread 与 spot/forward 分图；无效值为 `null` 且 Plotly `connectgaps=false`。
- Surface 图：按日期切片显示 smile 和 term structure；响应和 CSV 仍保留全部日期与全部点。
- 表格：同时显示 raw/effective IV 与 quality flags；无效 effective IV 显示为空。
- CSV：Compare 使用后端 CSV 路由；Surface 在浏览器从完整响应导出全部点。
- Methodology、Data Quality、Activity/Error：展示单位、公式、未复权 spot、排除政策、后台阶段、request ID、错误原因与 suggested action。
- Required disclosures：`query_builder`、`methodology`、`quality_panel`、`activity_console` 四个前端位置都有统一渲染器；仅按当前查询上下文显示适用条目。
- 离线 Plotly 5.24.1 已 vendor，并保留 MIT license；页面不向 CDN 请求资源。

## 用户确认的邻近坐标提示

页面遵守以下边界：

1. Compare 某日缺少精确坐标时，该日 IV 为空并显示缺失提示，不自动替换。
2. 用户可以切换到 Surface 并扩大查询范围查看实际返回坐标。
3. Surface 若有可用轴，会显示“最近返回 strike / expiry”；该信息明确标为参考，不会改写请求或统计。
4. Surface 若轴为空，只提示扩大范围，不伪造所谓最近值。

## 本阶段新增、且已在页面明示的展示边界

- 大 Surface 响应不截断；图表每次只画一个 business-date 切片。
- 单个 Surface 日期超过 1,000 点时，HTML 表格只显示前 1,000 点以避免页面卡顿；表格脚注明示该限制，内存中的完整响应和 CSV 导出不截断。
- RV 快捷档位只是输入建议；用户可输入任意不小于 2 的整数，非整数或小于 2 时页面明确拒绝，不取最近值。
- Spot 图、表头与 methodology 都标明 BNP 原始价格未复权，RV 是 price-return RV。

## Gate D

| Gate | 状态 | 证据 |
|---|---|---|
| 页面能发现全部已支持 mode | 通过 | 浏览器从 capability registry 生成 4 个 enabled mode；没有独立前端白名单 |
| IV 与 RV 标签完整 | 通过 | 实际标题为 `3M IV — K/S = 100%` 与 `RV 5 trading days (trailing)`，不使用裸 `IV/RV` 图例 |
| 非正 IV 明确提示 | 通过 | warning banner、quality flags、raw/effective 表格与 disclosure 同时覆盖 |
| 无效点不连接、不进入 summary | 通过 | effective IV 为 null、`connectgaps=false`；统计由后端已验证的有效序列生成 |
| 用户能看到后台阶段、错误原因和 suggested action | 通过 | Activity Console 渲染 validation/fetch/schema/normalization/analytics/frontend；标准化错误有独立错误页 |
| 页面明确显示 spot 未复权 | 通过 | 指标、图标题、表头、methodology、quality disclosure 多处显示 |

## 浏览器端到端检查

检查使用脱敏 `CORTEX_MODE=fixture`，因此没有调用 live BNP：

```text
Desktop viewport: 1440 × 1000
Mobile viewport: 390 × 844; document scroll width = 390
Enabled modes discovered: 4
Instrument search: QQQ matched 3
Compare: 6 rows; two Plotly chart containers rendered
Surface K/F: 2 maturities × 2 strikes; 4 table rows
Smile traces: 2
Term-structure traces: 2
Browser console errors: 0
Browser page errors: 0
```

Phase C 已有 live API probe；live 页面数值与独立 RV 复算、完整 CSV 对照属于 Phase E。

## 请用户重点检查

启动后打开 `http://127.0.0.1:8000/`：

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

建议只检查使用习惯，不需要逐项审代码：

1. Compare 与 Surface 两个入口是否直观。
2. 四种请求模式的字段命名和排列是否容易理解。
3. 最近 strike/expiry 的参考提示是否清楚表达“仅提示、不替代”。
4. 图表、表格、methodology、quality 和 activity 的信息密度是否可接受。
5. CSV 下载位置是否符合习惯。

确认后再进入 Phase E；页面交互细节也可以等实际使用后再调整。

## 验证命令

```powershell
python -m pytest -q
python -m ruff check app tests scripts
python -m ruff format --check app tests scripts
python -m compileall -q app scripts tests
git diff --check
```
