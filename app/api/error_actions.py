"""Suggested actions for each normalized error code (shown in the UI panel)."""

from __future__ import annotations

from app.clients.cortex.errors import ErrorCode

ACTIONS: dict[ErrorCode, str] = {
    ErrorCode.AUTHENTICATION_FAILED: "检查 .env 中的 BNP_CLIENT_ID / BNP_CLIENT_SECRET 是否正确且未过期。",
    ErrorCode.ENTITLEMENT_DENIED: "凭证无此数据权限,联系数据源支持(ecomeqd.production@bnpparibas.com)开通后重试。",
    ErrorCode.INSTRUMENT_NOT_FOUND: "用 GET /api/v1/instruments?q= 搜索正确的 instrument code 后重试。",
    ErrorCode.INVALID_REQUEST: "检查请求参数：日期区间、maturity rule / tenor、strike rule 与坐标取值；具体可用值以 capabilities 与 Cortex OpenAPI 为准。",
    ErrorCode.UPSTREAM_RATE_LIMITED: "上游限流,稍候片刻重试;避免短时间内重复大区间请求。",
    ErrorCode.UPSTREAM_UNAVAILABLE: "上游服务暂时不可用,稍后重试;持续失败请联系数据源技术支持。",
    ErrorCode.NO_DATA: "该参数组合无数据,尝试缩短日期区间或更换标的/期限。",
    ErrorCode.INVALID_SCHEMA: "上游响应未通过结构校验；请使用 requestId 联系开发方核对上游 API 版本。",
    ErrorCode.SCHEMA_CHANGED: "上游响应结构变化,请联系开发方升级解析器并核对 API 版本。",
    ErrorCode.AMBIGUOUS_DUPLICATE_DATE: "同一业务日期存在内容冲突的快照；请指定明确的 snapshot/close 规则后重试。",
    ErrorCode.PARSE_FAILED: "上游数据无法按请求坐标解析；请核对期限、strike 规则和 requestId。",
    ErrorCode.NORMALIZATION_FAILED: "标准化失败；原始响应已保留，请使用 requestId 联系开发方。",
    ErrorCode.STORAGE_FAILED: "本地缓存写入失败；请检查磁盘空间、目录权限和 requestId。",
    ErrorCode.CORRUPTED_RAW_CACHE: "本地 raw cache 校验失败；系统将忽略该缓存，请强制刷新或重建缓存。",
    ErrorCode.CALCULATION_FAILED: "计算异常,请联系开发方并提供 requestId。",
    ErrorCode.CONFIGURATION_ERROR: "配置缺失或无效,检查 .env(CORTEX_MODE/BNP_BASE_URL 等)。",
}


def action_for(code: ErrorCode) -> str:
    return ACTIONS.get(code, "请查看日志中的 requestId 并联系开发方。")
