# Phase B 完整请求模式验收

检查日期：2026-08-06  
依据：`volcurve_comprehensive_optimization_plan.md` 的 Phase B / Gate B。

## 当前结论

Phase B 与 Gate B **已通过**。四类请求模式的严格契约、独立 serializer、通用 surface parser、fixtures 和七组真实 API probes 均已验收；`/api/v1/capabilities` 已把全部四类模式标记为 `enabled=true`。

本次 live probe 首次运行时发现本地 `.env` 带 UTF-8 BOM，导致首行 `BNP_CLIENT_ID` 被解析成带隐藏字符的键。配置加载现显式使用 `utf-8-sig`，并增加 BOM 回归测试。修复后，沙箱外受控探针 7/7 通过。

## 已完成

- 四类互斥 Pydantic request models，覆盖 sliding K/F、sliding K/S、sliding delta、fixed/listed absolute strike、fixed/listed moneyness。
- BNP wire serializer 独立放在 Cortex adapter；domain 使用 `p25.0`，wire 才转换成 `p25_0`。
- BNP Cortex OpenAPI 1.60.0 对 K/F、K/S 使用全局固定的离散 moneyness 档位，不按标的或 tenor 改变。合法档位不代表所选标的、日期和期限一定返回有效数据；任意浮点数本地拒绝，不做取整或最近档位替代。
- 通用 surface parser 同时支持 matrix 与 vector，按 maturity-major 顺序标准化所有坐标。
- Delta axis 统一成 domain 的 `p25.0/c25.0`；fixed/listed maturity 按 ISO expiry date 验证。
- Compare 单序列只允许精确相同的 low/high 坐标；范围请求保留为 surface，不能静默选第一点。
- 新增四类 schema fixtures、market fixture 与 negative/zero/malformed/duplicate error fixtures。
- Capability 为每个模式返回 request model、serializer、parser、fixture、live probe 五项证据状态。

## 用户可见限制与假设契约

新增机器可读 `disclosures`；每一项都有 `frontendRequired=true` 和必须出现的 `frontendSurfaces`。Phase D 必须在 Query Builder、methodology、quality panel 或 activity console 中按指定位置展示。

当前登记内容包括：

- 非正/非有限 IV 的 raw/effective 分离与统计排除；
- 超过 500% 的正 IV 保留但标记；
- Forward RV future buffer、有效价格检查、12 次追加上限与 UTC 日期默认上限；
- RV 的 ddof=1、sqrt(252)、未复权 price-return 口径；
- 10% 对数收益只标记 outlier，不推断 corporate action；
- duplicate conflict hard fail；
- BNP 坐标网格与 delta convention 不自行推断；
- Compare 不做 nearest-coordinate fallback；
- BNP source timezone 未完成 live 确认前不拼接伪 UTC timestamp；
- HTTP retry 与 Retry-After 等待上限。

## Gate B

| Gate | 状态 | 证据 |
|---|---|---|
| 每种模式独立 Pydantic model | 通过 | 四类互斥模型覆盖 OpenAPI 组合；fixed/listed 由 literal 字段区分 |
| forbidden field 本地拒绝 | 通过 | `extra="forbid"` 与 union tests |
| wire request 与 BNP OpenAPI 一致 | 通过 | 七组 field-combination tests 与七组真实服务 probes |
| request hash 覆盖所有模式字段 | 通过 | mode、layout、delta、fixed/listed bounds 变更均改变 hash |
| 真实 API 每种模式至少一次 probe | 通过 | 七组均 PASS，每组返回 8 个观测日并通过通用 parser |

## Live probe

本次验收运行：

```powershell
python scripts/phase_b_modes_probe.py
```

脚本覆盖七组：sliding K/F、sliding K/S、sliding delta、fixed absolute、listed absolute、fixed moneyness、listed moneyness。它不会打印或保存 token、headers、raw body 或单点行情，只在 gitignored `data/normalized/phase_b_probe/report.json` 保存结构摘要。

七组均已 PASS；报告确认 `rawPayloadStored=false`，只保存模式、字段、观测日数、surface shape、点数及质量标记计数。对应 capability 的 `liveProbe` 和 `enabled` 已改为 true。

## 当前验证

```text
python -m pytest -q
69 passed

python -m ruff check app tests scripts
PASS

python -m ruff format --check app tests scripts
PASS

python -m compileall -q app scripts tests
PASS

git diff --check
PASS
```
