# Time Series Indicator Builder — 当前产品契约

初版日期：2026-08-07  
当前修订：2026-08-08

> 本文只描述**当前用户可见产品语义**。Phase F 早期的 5-chart、手输 Listed expiry、Load/Apply 等设计已废弃；cache/storage 细节只保留直接影响用户体验的部分，完整工程状态见 [`optimization_review_zh.md`](optimization_review_zh.md)。

## 1. 工作台模型

Time Series 以 observation date 为 X 轴：

- 全局选择新 indicator 的默认 instrument、开始/结束日期；所有 chart 共享日期范围；
- 最多 **8 个**上下排列 chart；
- 每个 indicator 独立保存 instrument、market coordinate、chart 归属和 enabled state；
- indicator 可编辑、复制、移动、启用/停用、删除；
- 一个 chart 可显示多个 indicator，不同 chart/indicator 可以使用不同 instrument；
- vol 类数据使用左轴，spot/forward 使用右轴；
- 任一 chart hover 时，其他 chart 只显示同一个**精确 observation date** 上实际存在的值；
- X zoom / reset 在 chart 间同步，Y axis 独立；
- board 保存布局和查询配置，重新打开后重新取数，不把旧 market response 当作当前数据保存。

浏览器 `localStorage` 只保存配置/布局/当前详情选择，不保存 token、credentials 或 raw market payload。

## 2. IV maturity

### Sliding tenor

例如 `1M`、`3M`。每个 observation date 按对应剩余期限取点；合法 tenor 由 capabilities/request contract 决定。

### Listed expiry

流程固定为：

1. instrument + observation date；
2. 自动请求该日 surface discovery；
3. 下拉展示当天实际 returned listed expiries；
4. 用户选择精确 expiry；
5. observation date 改变后重新 discovery，并使用 sequence guard 防止旧异步响应覆盖新日期。

不把不存在的日期或 expiry 替换成最近交易日/最近期限。

### Fixed date

`fixed` 仍是 backend/OpenAPI 的合法 maturity rule，并被 Bulk Maturity 等明确场景使用，但**不是主 indicator builder 的普通 maturity 入口**。

Fixed 也不代表“任意日历日期都有理论插值”；合法 request 如果上游没有该 coordinate，保持 `NO_DATA`。

## 3. IV strike

支持：

- **K/F percentage**：relative to forward；
- **K/S percentage**：relative to spot reference；
- **Delta**：仅允许 BNP contract 支持的 maturity/rule/delta code 组合；
- **Absolute strike**：必须为正数并保持精确请求。

对于 **Listed expiry + absolute strike**：

1. 先确定 observation date + listed expiry；
2. 自动读取该 expiry 实际 returned strikes；
3. 输入框给出 suggestions，同时允许用户自由输入正数；
4. 不存在的 strike 保持缺失/`NO_DATA`，不映射最近 strike。

`Sliding tenor + absolute strike` 当前不支持，也不会被静默改写成某个 listed expiry。

## 4. Wire/backend technical fields

`volatilityConvention` 和 `layout` 仍属于 Cortex wire contract，但不占主 indicator builder 的普通 UI：

- `volatilityConvention = bsVol` 默认；
- `layout = matrix` 默认；
- parser 仍按 contract 支持并标准化允许的 response layout；
- 实际 wire request 在 Request Audit / Methodology 中披露。

普通 UI 尽量 vendor-light，但 wire/audit 场景可以出现 BNP/Cortex 名称；这不是 correctness gate。

## 5. RV / Spot / Forward 数据路径

Cortex implied-volatility response 同时携带 spot 与 forward curve；项目当前没有独立 spot endpoint。

- **RV**：用 spot close-to-close log return 计算；reference IV request 只是取数 carrier，不进入 RV 公式；
- **Spot**：直接读取 returned spot；
- **Forward**：按所选 maturity 从 forward curve 精确取值；
- reference carrier 与 wire coordinate 在 Methodology / Request Audit 中披露；
- 不使用隐藏 fallback 或 nearest coordinate。

## 6. Data quality / error / stale

- raw IV 原值保留；非正/非有限 effective IV 置空并从 analytics 排除；极端正 IV 保留并标记；
- upstream `suggestedAction` 只从白名单字段脱敏展示，并区分 upstream/local source；
- empty covering-cache slice 返回 `NO_DATA`，不是 `200 []`；
- 429、upstream unavailable、`NO_DATA` refresh failure 在 historical archive 完整覆盖时可以返回 stale data；
- stale response 必须显示明显红色 **STALE DATA**，同时披露最近成功获取时间、refresh attempt 和失败原因；
- 400/401/403/schema/local-contract error 不允许使用 stale data 掩盖。

长期 archive/cache 具体语义见 [`optimization_review_zh.md`](optimization_review_zh.md)；licensed data 生命周期见 [`data_retention_policy_zh.md`](data_retention_policy_zh.md)。

## 7. Bulk Maturity

Bulk Maturity 有意支持：

- Sliding tenor；
- Fixed date。

这不改变主 indicator builder 仍以 Sliding + Listed 为普通入口。

规则：

- Fixed date 是精确 request coordinate，不保证上游存在；
- 前端只阻止已知 contract-invalid 组合，例如 Delta + Fixed、Absolute strike + Sliding；
- Listed expiry 不作为统一 bulk target，因为 expiry universe 随 instrument × observation date 变化，需要逐项 discovery；
- 从 Listed source indicator 批量改成 Sliding/Fixed 可以执行，只要目标组合本身合法。

## 8. 用户验收重点

1. 1–8 charts 的增加、删除、移动、缩放是否自然；
2. Sliding / Listed 的选择顺序是否直观；
3. observation date 改变时 Listed discovery 是否稳定、无旧日期回跳；
4. Listed + absolute strike suggestions 与自由输入是否同时可用；
5. 不存在的 date/expiry/strike 是否保持 `NO_DATA` 而非选最近值；
6. indicator 的独立 instrument、编辑/复制/启停是否符合研究习惯；
7. cross-chart hover 是否严格同日；
8. X zoom 同步、Y axis 独立、自定义统计和 board restore 是否稳定；
9. Request Audit / Methodology / Quality / Activity 是否对应当前 indicator；
10. stale fallback 是否足够醒目且 provenance 完整。

## 9. 验证原则

每个 PR 与 master push 的权威自动 Gate 是 GitHub Actions：install、compile、Ruff、pytest。本文不维护固定的 test-count 数字。

任何 UX 改动都不得改变以下 frozen rules：

- RV 数学定义；
- raw/effective IV 边界；
- 精确 coordinate 原则；
- invalid IV exclusion；
- 不做 silent nearest-coordinate replacement。