# BNP Cortex DataHub — 离线开发资料

来源:BNP Paribas CIB API Portal(https://developers.cib.bnpparibas.com),登录账号 dongkai.sun@cicc.com.cn 后下载。
下载日期:2026-08-06。API 版本:**1.60.0**(portal 标注 "Live",REST/JSON,Global Markets)。
机密级别:client-confidential(BNP 授权客户资料),不得外发、不得提交到公开仓库。

## 文件清单(docs/bnp/raw/)

| 文件 | 来源 URL | SHA-256 | 完整性 |
|---|---|---|---|
| cortex-openapi-1.60.0.yaml | /system/files/api-ref-files/2026-07/api-docs-1.60.0.RELEASE.yaml2987417600489388375.yaml | 748e4155…a9795f | 完整(1777 行,openapi 3.0.1) |
| CortexDataHubAPI-consumerOnBoarding.pdf | /sites/default/files/inline-files/CortexDataHubAPI-consumerOnBoarding_4.pdf | 9a74daef…06b709 | 完整(786 KB) |
| cortex-datahub-postman-src.zip | /sites/default/files/inline-files/cortex-datahub-postman-src_4.zip | 73e7e8dd…a25dd | 完整,已解压至 postman-src/ |
| cortex-datahub-python-src.zip | /sites/default/files/inline-files/cortex-datahub-python-src_7.zip | d72f731f…2723a1f | 完整,已解压至 python-src/ |
| cortex-datahub-client-java-src.zip | /sites/default/files/2025-07/cortex-datahub-client-src.zip | 960cb6d9…4a1e7 | 完整,已解压至 java-src/ |

另:`schemas/cortex-openapi.yaml` 为同一 YAML 的工作副本(供契约测试引用)。

## 从官方示例确认的关键事实(python-src/)

- 认证:`POST $BNP_TOKEN_URL`,HTTP Basic(clientId:clientSecret),`Content-Type: application/x-www-form-urlencoded`,body `grant_type=client_credentials` → 返回 `access_token` + `expires_in`(秒);到期前 60s 刷新。
- 请求头:`Content-Type: application/json`,`Accept: application/json`(或 `text/csv`),`Authorization: Bearer <token>`。
- `GET /v1/instruments` 支持 `?type=equity` 过滤。
- 请求体约定:`codeType` 为 `ric`(如 `BNPP.PA`)或 `bnpp`(如 `EU_STOXX50E`);**sliding strike 用下划线字符串**(如 `"lowStrike": "50_0"`);期限如 `1W`/`1M`/`3M`/`120M`;`layout: "matrix"`。
- 官方示例中 `requests` 使用 `verify=False`(企业代理/SSL 拦截环境);本项目默认开启证书校验,可用配置关闭。

## 支持联系方式

- 技术接入:ecomeqd.production@bnpparibas.com
- 数据销售:dl.cortex.datahub.sales.team@bnpparibas.com
