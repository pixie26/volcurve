# Phase F1 Compare Indicator Builder 验收说明

日期：2026-08-07

## 产品模型

Compare 不再要求用户先构造一份同时包含 IV、RV、Spot 的大请求。页面现在是一个时序研究工作台：

1. 全局选择新 indicator 的默认 instrument、开始日期和结束日期；日期范围由所有图表共享；
2. 主区域先显示一个以 observation date 为 X 轴的空白图，并可增加到最多 5 个上下排列的坐标；
3. 左侧逐个构建 indicator；
4. 每个 indicator 独立保存 instrument 和所属坐标，保存后可移动、启用、停用或删除；
5. 每个坐标可显示多个 indicator，不同坐标及 indicator 可以使用不同标的；
6. 波动率使用各坐标左轴，spot/forward 使用右轴；
7. 任一图表 hover 时，其他图表显示同一天实际存在的所有 indicator 数值；
8. 鼠标矩形框选执行 zoom；X 日期范围同步到其他图表，Y 范围仍由各图独立缩放。

当前不设置 indicator 数量上限，图表坐标数量上限为 5。indicator 配置、独立 instrument、所属坐标、启用状态、图表数量、当前详情选择以及全局日期范围保存在当前浏览器的 `localStorage`；页面刷新或之后重新打开时会恢复，并重新请求所有激活项。旧版单图保存会迁移到坐标 1。该保存不跨浏览器/profile/origin，清除站点数据也会删除。行情响应、token、凭证和 raw payload 不写入浏览器持久化存储，避免把旧行情伪装成当前响应。

## 多坐标交互规则

- “添加坐标”逐个增加图表，达到 5 个后按钮禁用；没有自动合并或复用隐藏坐标。
- 任意空坐标都可删除；若其中仍有 indicator，会拒绝删除并提示先在保存卡片中移动或删除。删除空坐标后，更高坐标编号自动顺移，indicator 配置同步更新且不会丢失。
- 同日 hover 只显示各响应中精确存在的日期，不向前填充、不插值，也不选择最近交易日。
- 矩形 zoom 同步 X 轴日期范围，因此不同标的仍保持时间对齐；Y 轴不跨图同步，避免把价格与波动率或数量级差异很大的标的压缩到不可读。
- 双击恢复 X 轴自动范围时，同样同步到其他坐标。

## 图表之外的完整结果

新 Compare 只替换查询构建和总图，没有删除旧版结果信息。任一 indicator 加载完成后，可从保存卡片点击“查看详情”，或在结果区的“当前指标详情”下拉切换。每个 indicator 独立显示：

- 完整逐日数据表，包括图中 selected value、spot、forward、raw/effective IV、RV 与 quality flags；
- 请求 maturity/strike、Vol convention、Layout、取数载体、IV/RV 公式和数据源；
- data quality 汇总与逐 flag 计数；
- 后端 activity events、request ID，以及浏览器接收完成事件；
- 与该 indicator 实际语义匹配的 methodology、quality、activity disclosures；
- 当前所选 indicator 的 CSV 下载。

多 indicator 不会合并后台记录；详情区始终明确对应一个选中的 indicator。

## IV maturity 语义

- `sliding` 是 BNP OpenAPI 的 maturity rule，不是本项目创造的。`3M` 表示每个观察日都取当时剩余期限约为 3M 的理论期限。
- Sliding tenor 输入允许键盘输入，但 BNP OpenAPI 1.60.0 只接受 capability registry 返回的官方 tenor。输入 `13D` 之类的非官方值会本地明确拒绝，不伪装成行情缺失。
- `fixed` 与 `listed` 都是 BNP OpenAPI maturity rule。官方组合表把 `fixed` 描述为允许 theoretical maturities 的固定日期模式，把 `listed` 描述为不包含 theoretical maturities 的实际挂牌期限模式。
- Fixed/Listed expiry 均允许手输任意合法日期。BNP 没有返回该精确点时保持缺失，不改成最近 expiry。
- 选择 `listed` 时可按 observation date 请求一次无边界 fixed-strike surface，查看 BNP 当天实际返回的 expiry/strike。只有用户点击应用才写入草稿。

## IV strike 语义

- Percentage moneyness 继续区分 `K/F`（relative to forward）和 `K/S`（relative to spot reference）。
- Percentage 可以键盘输入，但必须命中 BNP OpenAPI 的离散档位；不取整、不选最近值。
- Delta 只与 sliding maturity 组合，并只接受 BNP 官方 put/call delta codes。
- Absolute strike 接受任意正数。精确 strike 不存在时保持缺失。
- Listed + absolute strike 可通过坐标发现加载实际 expiry，再查看该 expiry 下 effective IV 有效的 strikes；无效点不进入下拉，但保留质量状态。

## Vol convention 与 Layout

这两个字段都来自 BNP OpenAPI，不是本项目发明的，并按用户要求继续保留在主 indicator 表单：

- `volatilityConvention`：默认 `bsVol`；OpenAPI 说明通常只有 `bsVol` 可用，`bnppVol` 只用于 dividend volatility。
- `layout`：控制 BNP 返回 surface 的结构。`matrix` 是 maturity rows × strike columns；`vector` 是按同一坐标顺序展开的扁平数组。项目 parser 会把两种结构标准化，layout 不改变指标的经济含义。

每个 indicator 独立保存这两个选择，并在保存卡片中披露，不做隐藏或锁定。

## 非 IV indicator 的数据路径

当前 Cortex implied-volatility response 同时携带 spot 和 forward curve，项目没有独立 spot endpoint。因此：

- RV 使用 BNP spot 计算，并以 `3M K/F 100%` IV request 作为取数载体；该 IV 坐标不进入 RV 公式；
- Spot 使用同一个 reference request，只读取原始未复权 spot；
- Forward 使用用户所选 maturity，并以 `K/F 100%` 请求取得对应 forward curve；
- 用户仍可为这些载体选择 Vol convention 与 Layout；错误 entitlement/组合按 BNP 原始错误明确显示。

这些不是静默假设：builder note 与保存后的 indicator 卡片都会显示载体坐标、未复权边界和 wire 参数。

FX 是 instrument 类型，不是一个独立 indicator。未来开放 FX instrument catalogue 后，仍使用 Spot、Forward、IV 等指标；当前 catalogue 只开放 equity，本阶段不伪造没有后端语义的 `FX indicator`。

## 用户检查项

1. 1–5 个上下图表的添加顺序和高度是否符合预期。
2. IV maturity 先选 sliding/fixed/listed，再输入期限的顺序是否自然。
3. Strike 先选 percentage/delta/absolute；percentage 再选 K/F 或 K/S，是否自然。
4. Vol convention 与 Layout 的位置和解释是否应继续保持现状。
5. 每个 indicator 的独立 instrument、目标坐标及保存卡片移动功能是否自然。
6. 鼠标经过任一图表时，其他图表是否清楚显示同一天的数据；某标的当天缺失时是否正确保持缺失。
7. 框选矩形后所有图表 X 轴是否同步，而各图 Y 轴是否仍适合自己的数值范围。
8. 添加、启用/停用、删除及“刷新激活项”是否符合对“保存 indicator”的理解。
9. 刷新或关闭后重新打开页面，图表数量、indicator instrument、所属坐标、日期和启用状态是否恢复。
10. 保存卡片“查看详情”和结果区下拉能否清楚切换数据表、方法、质量、activity 与 disclosures。
11. Spot/RV 的 reference IV request 提示是否足够清楚。

本阶段没有修改后端数值公式、精确坐标语义、无效 IV 排除、RV 任意整数窗口或 raw/effective 数据边界。

## 当前验证

```text
JavaScript syntax check: PASS
python -m pytest -q: 101 passed
ruff check / format check: PASS
compileall: PASS
git diff --check: PASS（仅 Windows LF→CRLF 提示）
fixture HTTP smoke: health 200；页面与 compare-builder.js 200
fixture compare smoke: US_QQQ 与 US_SPY 均返回 7 rows 且 source code 与独立请求一致；activity 6；disclosures 17；compare CSV 200
```

当前任务没有暴露应用内浏览器控制接口，因此没有把点击与视觉检查误报为自动通过。脱敏 fixture 服务已启动在 `http://127.0.0.1:8000/`，最终 Gate 仍需用户按上面的检查项验收。
