# Phase F Time Series Indicator Builder — 当前产品语义与验收说明

初版日期：2026-08-07  
当前修订：2026-08-08

> 本修订覆盖 2026-08-07 文档中的旧 UI 描述。后端保留的 legacy/OpenAPI 能力与当前主 UI 暴露的能力需要区分；不要再把旧文档里的 Fixed/Listed 手输、Load/Apply 或 5-chart 上限当成当前产品契约。

## 产品模型

Time Series 是一个以 observation date 为 X 轴的时序研究工作台：

1. 全局选择新 indicator 的默认 instrument、开始日期和结束日期；日期范围由所有图表共享；
2. 主区域最多支持 **8 个**上下排列的坐标；
3. 左侧逐个构建 indicator；
4. 每个 indicator 独立保存 instrument、所属坐标和启用状态，保存后可编辑、复制、移动、启用/停用或删除；
5. 每个坐标可显示多个 indicator，不同坐标及 indicator 可以使用不同标的；
6. 波动率使用左轴，spot/forward 使用右轴；
7. 任一图表 hover 时，其他图表显示同一个**精确 observation date** 上实际存在的 indicator 数值；
8. 矩形 zoom 同步各图 X 日期范围，Y 轴仍独立缩放；
9. board 可保存 indicator 配置、坐标布局和日期范围，载入后重新取数，不把旧行情持久化成当前响应。

indicator 配置、独立 instrument、所属坐标、启用状态、图表布局、当前详情选择以及全局日期范围保存在浏览器 `localStorage`。行情响应、token、凭证和 raw payload 不写入浏览器持久化存储。

## 多坐标交互规则

- “添加坐标”逐个增加图表，达到 8 个后按钮禁用；
- 空坐标可删除；若其中仍有 indicator，会要求先移动或删除；
- 同日 hover 不向前填充、不插值、不选择最近交易日；
- X zoom/双击恢复同步到全部图，Y 轴保持各自范围；
- 每条 indicator 可单独查看详情、方法、质量、activity、request audit 与 CSV。

## IV maturity 语义

### 主 UI 暴露的两种模式

- **Sliding tenor**：例如 `1M`、`3M`。每个 observation date 都按对应剩余期限取理论期限点；合法 tenor 以 capabilities/OpenAPI 为准。
- **Listed expiry**：用户先给 observation date，系统自动查询该日实际返回的 listed expiries，再由用户从可用 expiry 中选择精确到期日。

### Fixed 的当前定位

`fixed` 仍存在于 BNP OpenAPI、后端 request model 和 legacy 配置兼容层中，但**不作为新建 indicator 主 UI 的普通 maturity 入口**。

Fixed 的含义也不是“任意日历日期都有理论插值”。OpenAPI 的 fixed/listed 语义都受实际上游可用 maturity 集合约束；当请求坐标不存在时保持缺失/NO_DATA，不自动选择最近 expiry。

### Listed expiry discovery

当前 Listed expiry 不再使用旧的“手输日期 → Load → Apply”流程：

1. 用户选择 instrument 与 observation date；
2. 页面自动发起单日 surface discovery；
3. 下拉直接展示该日实际返回的 listed expiries；
4. 用户选择一个精确 expiry；
5. observation date 改变时重新 discovery，并用 request sequence guard 防止旧异步响应覆盖新日期。

不会静默把用户日期改成最近交易日，也不会把不存在的 expiry 替换成附近期限。

## IV strike 语义

- Percentage moneyness 区分 `K/F`（relative to forward）和 `K/S`（relative to spot reference）；
- Delta 只在 BNP 支持的 maturity/rule 组合下使用，并接受官方 put/call delta codes；
- Absolute strike 接受正数，但精确 strike 不存在时保持缺失，不自动映射最近值；
- **Listed expiry + absolute strike**：选定 observation date 与 listed expiry 后，页面自动读取该 expiry 下实际返回的 strikes；strike 输入框同时支持自由键入与下拉建议，不需要单独的 Load/Apply；
- 不支持的 `Sliding tenor + absolute strike` 不会被静默改写成某个 listed expiry。

## Volatility convention 与 Layout

`volatilityConvention` 与 `layout` 仍属于 BNP wire/backend contract，但已从主 indicator builder 的普通交互中移出：

- `volatilityConvention` 默认 `bsVol`；
- `layout` 默认 `matrix`；parser 仍支持合同允许的返回布局并标准化；
- 实际 wire 值继续出现在 Request Audit / Methodology 中；
- legacy 配置仍可被后端理解，但新 UI 不要求用户每天手动选择这两个技术字段。

因此，2026-08-07 文档中“这两个字段继续保留在主 indicator 表单”的表述已经废弃。

## 非 IV indicator 的数据路径

当前 Cortex implied-volatility response 同时携带 spot 和 forward curve，项目没有独立 spot endpoint：

- RV 使用 spot 计算，并以 reference IV request 作为取数载体；该 IV 坐标不进入 RV 公式；
- Spot 读取原始 spot；
- Forward 按用户所选 maturity 从对应 forward curve 读取；
- reference carrier、wire 参数与方法边界在 Methodology / Request Audit 中披露；
- entitlement、NO_DATA、schema 等错误通过统一错误契约返回，不做隐藏 fallback。

## Error / cache / upstream 语义

- 上游 `suggestedAction` 若存在，只对白名单字段做脱敏后保留，并标记 `suggestedActionSource=upstream`；否则使用本地 fallback；
- covering cache 裁剪后若目标日期没有 observation，Surface 返回 `NO_DATA`，不会因 cache 命中而返回 `200 snapshots=[]`；
- 相同 request hash 的并发请求 single-flight 合并；不同真实 Cortex HTTP attempts 进程内最多 4 个同时执行；
- cache hit / fixture 不占 upstream 并发 slot。

## Bulk Maturity 当前语义

Bulk Maturity **有意支持** `Sliding tenor` 与 `Fixed date` 两种目标；这不改变主 indicator builder 仍以 Sliding + Listed 为普通新建入口的产品契约。

- Fixed date 是一个精确 Cortex request coordinate，不代表任意日历日期都存在数据；合法请求可正常发出，坐标不存在时由后端返回 `NO_DATA`，前端不预判、也不替换成最近期限；
- 只在组合已知违反数据契约时前端阻止，例如 `Delta IV + Fixed`、`Absolute strike IV + Sliding`；
- `Listed expiry` 不作为统一 bulk target，因为可用 expiry universe 随 underlying × observation date 变化，需要逐项 discovery；
- 一个当前使用 Listed expiry 的 source indicator，可以批量改成 Sliding 或 Fixed，只要目标组合本身合法。

## 用户验收重点

1. 1–8 个图表的添加、删除、移动与高度是否符合使用习惯；
2. Sliding tenor / Listed expiry 的选择顺序是否自然；
3. observation date 改变时 listed expiries 是否自动且稳定刷新，不发生旧日期回跳；
4. Listed + absolute strike 是否自动给出 strike suggestions，同时允许键盘输入；
5. 不存在的 expiry/strike/date 是否明确保持 NO_DATA，而不是选最近值；
6. 每个 indicator 的独立 instrument、目标坐标、编辑/复制/启停功能是否自然；
7. hover 任一图表时，其他图是否只显示同一天精确存在的数据；
8. X 轴同步 zoom、各自 Y 轴、自定义统计列与 board 恢复是否符合预期；
9. Request Audit / Methodology / Quality / Activity 是否准确对应当前 indicator；
10. 普通 UI 尽量 vendor-light，但 BNP/Cortex 名称不作为 correctness hard gate，wire/audit 场景可按需要出现。

## 验证口径

GitHub Actions 已作为当前自动 Gate。每个 PR 与每次 push 到 `master` 自动执行：

```text
install .[dev]
compileall
Ruff
pytest
```

不要在本文长期维护固定的“xx passed”测试数量；新增测试后该数字会自然变化，GitHub Actions 的最新 green run 才是权威自动验证证据。

本阶段没有改变 RV 数学定义、IV raw/effective 边界、精确坐标原则、invalid IV 排除规则或不做最近值替代的基本原则。
