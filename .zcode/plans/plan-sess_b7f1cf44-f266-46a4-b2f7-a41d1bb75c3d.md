# Cortex Vol Analytics — 最终执行计划

## 基线规格
用户粘贴的《最终实施计划》1–16 节全文作为验收基线(范围、目录结构、Gates、质量标记、错误分类、安全与部署、扩展路线均按原文执行),以下为经双方确认的修订与执行方式。

## 已核实 API 事实
- 认证:Basic(clientId:secret)→ `POST https://api.cib.bnpparibas.com/oauth2/v1/token` → bearer,内存缓存+提前 60s 刷新,不落盘、不进日志
- 生产 base:`https://api.cib.bnpparibas.com/gm-cortex-datahub`(OAS 页另显示 sandbox host `api.sandbox.cib.bnpparibas.com/gm-cortex-datahub-internet`,仅作排查备选)
- `POST /v1/implied-volatility` 响应按日期含 `date/time/timeZone/spot/maturities[]/strikes[]/forwardCurve[]/zcCurve[]/matrix[][]/vector[]`;`Accept` 控制 json/csv
- 凭证:用户已提供 clientId/clientSecret → 写入 `.env`;`.env`、`data/raw/` 进 `.gitignore`,**先于首次 git commit**;任何输出/报告不回显

## 确认的修订(相对基线)
1. **RV 预热**:拉取起始日 = 用户起始日 − ceil(RV窗口×7/5) − 10 日历日(63 sessions≈89 日历日+节假日余量+1 个额外价格点);显示区间严格不变;forward RV 尾部留空不补零
2. **RV 口径**:ddof=1、去均值(=Excel STDEV.S),log return,√252 年化;公式小字显示在页面口径栏与 CSV 头;RV 作为可开关 indicator(页面 Show/Hide RV 控件)
3. **Matrix orientation**:Phase 1 用 2 期限 × 2 strike 小矩阵探针一次确定方向,禁止 matrix[0][0];IV 单位(% vs 小数)同探针确认,写入 data_contract.md
4. **项目根**:直接在 `D:\Desktop\py\volcurve` 落地,不嵌套子目录
5. **Git**:先 `.gitignore`(含 .env、data/、__pycache__)再首次 commit
6. **CSV 元数据**:写文件头 `# key: value` 注释行(参数/来源/版本/时间戳/计算口径),不用 companion file
7. **存储**:raw 为权威源,normalized/DuckDB 可从 raw 重建,README 写 recovery 说明
8. **Python**:pyproject 要求 `>=3.11`(先查本机版本)
9. **前端**:Plotly bundle 一次性联网下载到 `static/vendor/`,之后全离线;不用公共 CDN
10. **测试深度**:单元 + 契约(fixture)+ 真实 API 探针 + 浏览器人工页面验证;不建自动化 e2e 框架
11. **健康检查**:/health/ready 的 Cortex 连通性用缓存结果,不触发 token 获取

## 执行顺序与逐步验收(关键:每 Gate 停下,用户确认后再继续)
- **Phase 0** → 验收点 A:docs/bnp/ 资料清单(含 SHA-256)、.env 就位、Gate 0 结果(token 获取、expiry 解析、/v1/instruments 成功、entitlement 确认、无 secret 泄漏检查)。若 403 → 停止并报告
- **Phase 1** → 验收点 B:`qqq_probe.csv`(≥5 有效日期,K/S 与 K/F 两种口径 IV、spot、forward、maturity、quality flags),matrix orientation 与 IV 单位结论
- **Phase 2** → 验收点 C:同一请求连跑两次(live→cache),标准化结果一致;raw/normalized 文件落盘展示
- **Phase 3** → 验收点 D:RV/IV−RV/percentile/z-score/correlation 计算结果 + 独立脚本复算一致(容差 1e-10);单测通过
- **Phase 4** → 验收点 E:/api/v1/instruments、/api/v1/vol/compare、/api/v1/vol/compare.csv、/health/* 可用(给用户 curl 示例自验)
- **Phase 5** → 验收点 F:页面截图演示(默认 preset:QQQ/近1年/3M/K=F 100%/63 sessions/trailing),图表、表格、summary cards、口径栏齐全
- **Phase 6–7** → 验收点 G:validation_report.md(10 日期抽查、RV 复算、页面-表格-CSV 一致性、corporate-action 状态)、secret scan 结果、启动说明

## 主要风险
- entitlement:凭证是否开通 Cortex DataHub 权限,Gate 0 即知;403 则停
- QQQ 的 BNP code 从 /v1/instruments 实况解析,不硬编码
- corporate-action adjustment 若无法确认,页面显示 unverified,不作正式 VRP 结论
