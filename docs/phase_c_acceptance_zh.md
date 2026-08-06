# Phase C REST API 验收

检查日期：2026-08-06  
依据：`volcurve_comprehensive_optimization_plan.md` 的 Phase C / Gate C。

## 当前结论

Phase C 与 Gate C **已通过**。`instruments`、单坐标 `compare`、多坐标 `surface`、CSV、统一错误响应、request ID、activity events 与 health 已接入 FastAPI；fixture integration tests 和受控 live API probe 均通过。Phase D 尚未开始。

## 已完成接口

```http
GET  /api/v1/capabilities
GET  /api/v1/instruments?q=QQQ&type=equity&maxResults=50
POST /api/v1/vol/compare
POST /api/v1/vol/surface
POST /api/v1/vol/compare.csv
GET  /health/live
GET  /health/ready
```

- `compare` 只接受一个精确 IV 坐标，并返回 IV、RV、spread、ratio、summary、methodology、quality、activity 与 disclosures。
- `surface` 保留请求返回的全部 strike/maturity，不选择第一点、不取邻近点、不静默截断。
- JSON 与 CSV 共享同一个 `CompareResponse` 结果；volatility 在 API/CSV 边界统一为 percent。
- 每个响应带 `X-Request-ID`；错误只返回标准化 `code/stage/message/suggestedAction/requestId`。
- 浏览器响应不包含 token、Authorization、BNP raw body、stack trace 或本地路径。

请求 envelope 为：

```json
{
  "volatilityRequest": {
    "code": "US_QQQ",
    "start_date": "2026-07-26",
    "end_date": "2026-08-05",
    "maturity_rule": "sliding",
    "strike_rule": "relative_to_spot_ref",
    "low_strike": 100,
    "high_strike": 100,
    "low_maturity": "3M",
    "high_maturity": "3M"
  },
  "rvWindowSessions": 5,
  "rvAlignment": "trailing"
}
```

## 本阶段发现并修复的 live 边界

Fixed/listed compare 为计算 trailing RV 会请求展示日前的 warm-up 区间。BNP 在部分历史日期可能返回合法的空 surface，代表指定 expiry/strike 当日不可用。

当前规则：

- 空坐标轴且无 IV 值：按缺失数据处理，保留 `MISSING_IV`/坐标 mismatch flags；
- 空坐标轴却带 IV 值：仍视为 `SCHEMA_CHANGED` 并 hard fail；
- 不使用邻近 expiry、strike 或 moneyness 替代。

## 用户可见限制与假设

所有新增限制继续登记在 `/api/v1/capabilities.disclosures`，并带 `frontendRequired=true`：

- RV 接受任意不小于 2 的整数 trading-session 窗口，不设产品上限；前端快捷档位为 5、10、20、40、60、90、120、250、500；自定义值原样计算，不取最近值；非整数或小于 2 的请求明确拒绝；最小值 2 来自当前 `ddof=1` 样本标准差公式；
- instrument catalogue 当前只开放 equity；默认返回 50 项、单次最多 200 项，`hasMore` 明示是否截断；
- 非有限 raw IV 在 JSON/CSV 中用 `NaN`、`Infinity`、`-Infinity` 字符串保留，effective IV 为 null；
- 未设置 fixed/listed 边界可能生成大 surface；超过 100,000 点产生 `LARGE_SURFACE_RESULT`，但不静默截断；
- health ready 不主动获取 token，只显示最近 live 请求的成功或连接/认证失败 beacon；业务性 NO_DATA/schema 错误不冒充网络中断；
- 原 Phase A/B 的 invalid IV、forward RV、未复权 spot、HTTP retry、坐标网格等 disclosures 全部随响应返回。

Phase D 必须在 Query Builder、methodology、quality panel 或 activity console 中实际渲染这些项目。

## Gate C

| Gate | 状态 | 证据 |
|---|---|---|
| fixture mode 全接口可用 | 通过 | integration tests 覆盖 health、capabilities、instruments、四类 surface、四类 compare、CSV 与 errors |
| live QQQ compare 可用 | 通过 | K/S 3M 100% compare 返回 8 个展示日期 |
| live delta/fixed/listed 样例可用 | 通过 | 三种 compare 均通过；fixed/listed 先由 surface 精确选择真实坐标 |
| API/CSV 数值一致 | 通过 | 8 行逐行检查 IV、RV 及空值表示一致 |
| 无敏感信息返回浏览器 | 通过 | synthetic secret/bearer/Windows path 回归测试；当前凭证值在 `.env` 外源码/测试/文档中 0 命中 |

## Live probe

```powershell
python scripts/phase_c_api_probe.py
```

最终 8/8 PASS：instruments、K/S compare、delta compare、fixed surface/compare、listed surface/compare、CSV consistency。脱敏报告位于 gitignored 的 `data/normalized/phase_c_probe/report.json`，明确记录 `rawPayloadStoredInReport=false` 与 `marketValuesStoredInReport=false`。

## 当前验证

```text
python -m pytest -q
76 passed

python -m ruff check app tests scripts
PASS

python -m ruff format --check app tests scripts
PASS

python -m compileall -q app tests scripts
PASS

git diff --check
PASS（仅 Git 的 LF/CRLF 提示）
```

## 请用户重点检查

1. `compare` 与 `surface` 分离是否符合使用习惯；compare 不允许范围，surface 不自动降维。
2. `CompareResponse` 的 percent 单位、methodology、dataQuality、activity 与 disclosures 是否足够供前端展示。
3. fixed/listed 历史空 surface 按“缺失”处理且绝不选邻近坐标，是否符合预期。
4. 大 surface 不截断、仅警告并建议缩小范围，是否符合预期。
5. 确认后再进入 Phase D Web MVP。

### Phase C 验收修订

用户确认 RV 窗口不应采用固定白名单或人为上限。原 capability 示例已修正为“快捷档位 + 任意自定义整数”：快捷档位仅用于前端选择，不限制 API；例如输入 22 就计算 22-session RV，不替换成 20。唯一最小值 2 是当前 `ddof=1` 样本标准差的数学要求。
