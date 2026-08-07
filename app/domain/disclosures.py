"""Machine-readable methodology, filtering, and operational disclosures.

These entries are part of the backend contract.  The future Web phase must
render applicable entries in its methodology/quality/activity surfaces instead
of leaving limits and assumptions only in source code or documentation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

SUSPICIOUS_IV_THRESHOLD_DECIMAL = 5.0
RETURN_OUTLIER_THRESHOLD_LOG = 0.10
FORWARD_MAX_EXTENSION_REQUESTS = 12
RV_BUFFER_EXTRA_CALENDAR_DAYS = 10
HTTP_MAX_RETRIES = 4
HTTP_MAX_RETRY_AFTER_SECONDS = 60
LARGE_SURFACE_POINT_WARNING = 100_000


class Disclosure(BaseModel):
    id: str
    title: str
    category: Literal["methodology", "filter", "assumption", "limit", "data_quality"]
    severity: Literal["info", "warning"]
    summary: str
    details: list[str]
    appliesTo: list[str]
    frontendSurfaces: list[str]
    frontendRequired: bool = True


DISCLOSURES = (
    Disclosure(
        id="invalid_iv_exclusion",
        title="无效 IV 排除规则",
        category="filter",
        severity="warning",
        summary="非正或非有限 IV 保留原值，但有效 IV 置空并从所有统计中排除。",
        details=[
            "rawImpliedVol 保留数据源原值。",
            "impliedVol 设为 null；不做 abs、clip、zero-fill 或前向填充。",
            "不参与 spread、ratio、percentile、z-score 或 correlation。",
        ],
        appliesTo=["implied_vol", "compare", "surface"],
        frontendSurfaces=["methodology", "quality_panel", "activity_console"],
    ),
    Disclosure(
        id="suspicious_iv_retained",
        title="极端正 IV 保留规则",
        category="assumption",
        severity="warning",
        summary="正 IV 高于 500% 仍参与计算，但标记为 SUSPICIOUS_IV_EXTREME。",
        details=["阈值为 decimal IV > 5.0。", "该标记不是数据错误结论。"],
        appliesTo=["implied_vol", "compare", "surface"],
        frontendSurfaces=["methodology", "quality_panel", "activity_console"],
    ),
    Disclosure(
        id="forward_rv_fetch_extension",
        title="Forward RV 未来数据范围",
        category="limit",
        severity="info",
        summary="Forward RV 会在展示区间后追加数据；不足时保持 null。",
        details=[
            "初始 future buffer = ceil(window sessions × 7 / 5) + 10 calendar days。",
            "按最后展示日开始的 window + 1 个有效价格检查覆盖。",
            f"最多追加 {FORWARD_MAX_EXTENSION_REQUESTS} 次，且不超过已知可用日期。",
            "未显式提供可用日期时，后端以当前 UTC 日期作为保守上限。",
        ],
        appliesTo=["realized_vol", "forward"],
        frontendSurfaces=["methodology", "activity_console"],
    ),
    Disclosure(
        id="rv_estimator",
        title="RV 估计口径",
        category="methodology",
        severity="info",
        summary="RV 使用未复权 spot 的 close-to-close 对数收益与样本标准差。",
        details=[
            "return = log(S_t / S_{t-1})。",
            "样本标准差 ddof=1、去均值、sqrt(252) 年化。",
            "缺失价格或收益不填充，受影响窗口返回 null。",
        ],
        appliesTo=["realized_vol", "compare"],
        frontendSurfaces=["methodology"],
    ),
    Disclosure(
        id="unadjusted_price_return",
        title="价格未做公司行动或分红调整",
        category="assumption",
        severity="warning",
        summary="Spot 来自数据源原始未复权价格，RV 是 price-return RV。",
        details=[
            "未接入 corporate-action calendar。",
            "未计算 dividend-adjusted 或 total-return RV。",
        ],
        appliesTo=["spot", "realized_vol", "compare"],
        frontendSurfaces=["methodology", "quality_panel"],
    ),
    Disclosure(
        id="return_outlier_not_corporate_action",
        title="大幅收益只作异常提示",
        category="data_quality",
        severity="warning",
        summary="单期绝对对数收益超过 10% 标记 RETURN_OUTLIER，不等同已确认公司行动。",
        details=["价格不自动调整或删除。", "需要外部事件数据才能确认原因。"],
        appliesTo=["spot", "realized_vol"],
        frontendSurfaces=["quality_panel", "activity_console"],
    ),
    Disclosure(
        id="duplicate_resolution",
        title="重复业务日期处理",
        category="data_quality",
        severity="warning",
        summary="完全相同记录去重；同日内容冲突会终止查询。",
        details=["冲突错误码为 AMBIGUOUS_DUPLICATE_DATE。"],
        appliesTo=["compare", "surface", "cache"],
        frontendSurfaces=["quality_panel", "activity_console"],
    ),
    Disclosure(
        id="exact_coordinate_no_fallback",
        title="单序列只接受精确坐标",
        category="limit",
        severity="info",
        summary="Compare 单序列必须指定同一 low/high 坐标，不会自动选择第一个或邻近点。",
        details=[
            "范围请求保留为 surface；不能隐式降维成单序列。",
            "返回轴缺少精确坐标时标记 MATURITY_MISMATCH/STRIKE_MISMATCH。",
        ],
        appliesTo=["compare", "request_builder"],
        frontendSurfaces=["query_builder", "methodology", "activity_console"],
    ),
    Disclosure(
        id="bnp_coordinate_grid",
        title="数据源坐标网格限制",
        category="limit",
        severity="info",
        summary="数据源 OpenAPI 1.60.0 对 moneyness、delta 和 sliding maturity 使用全局固定枚举。",
        details=[
            "枚举不按标的或 tenor 改变，但合法坐标不代表所选标的、日期和期限一定返回有效数据。",
            "前端必须从 capabilities 读取合法值；系统不做取整或最近档位替代。",
            "Delta 定义来自数据源 API，本系统不自行推断 delta convention。",
        ],
        appliesTo=["request_builder", "surface"],
        frontendSurfaces=["query_builder", "methodology"],
    ),
    Disclosure(
        id="source_timezone_not_inferred",
        title="Source time 暂不推断为 UTC instant",
        category="assumption",
        severity="info",
        summary="在数据源 timeZone 实际格式完成 live 验证前，source time 与 timezone 分开保留。",
        details=[
            "sourceTimestamp 保持 null，避免用字符串拼接制造错误时刻。",
            "上游合约写明 time 仅在 intraday 数据出现；本系统只请求日频 EOD 历史，"
            "因此 time 为空是正常的，不计为质量问题。",
        ],
        appliesTo=["source_metadata"],
        frontendSurfaces=["methodology", "activity_console"],
    ),
    Disclosure(
        id="bounded_http_retries",
        title="上游重试有界",
        category="limit",
        severity="info",
        summary="上游限流或 5xx 只进行有界重试，失败会返回标准化错误。",
        details=[
            f"最多重试 {HTTP_MAX_RETRIES} 次。",
            f"Retry-After 单次等待上限 {HTTP_MAX_RETRY_AFTER_SECONDS} 秒。",
        ],
        appliesTo=["upstream_fetch"],
        frontendSurfaces=["activity_console"],
    ),
    Disclosure(
        id="nonfinite_iv_wire_encoding",
        title="非有限 IV 的导出表示",
        category="data_quality",
        severity="warning",
        summary="NaN 或正负 Infinity 无法作为标准 JSON 数字传输，API/CSV 使用同名字符串保留。",
        details=[
            "rawImpliedVol 使用 NaN、Infinity 或 -Infinity 字符串。",
            "impliedVol 仍为 null，并带 INVALID_IV_NON_FINITE 标记。",
        ],
        appliesTo=["compare", "surface", "csv"],
        frontendSurfaces=["methodology", "quality_panel"],
    ),
    Disclosure(
        id="rv_window_grid",
        title="RV 窗口范围与快捷档位",
        category="limit",
        severity="info",
        summary="RV 接受任意不小于 2 的整数 trading-session 窗口，不设产品上限。",
        details=[
            "前端快捷档位为 5、10、20、40、60、90、120、250、500。",
            "自定义整数按原值计算，不自动取最近窗口。",
            "非整数或小于 2 的请求会被明确拒绝；最小值来自 ddof=1 样本标准差定义。",
        ],
        appliesTo=["realized_vol", "compare", "request_builder"],
        frontendSurfaces=["query_builder", "methodology"],
    ),
    Disclosure(
        id="instrument_search_page_limit",
        title="Instrument 搜索返回上限",
        category="limit",
        severity="info",
        summary="单次 instrument 搜索最多返回 200 项，并明确返回 hasMore。",
        details=["默认返回 50 项；前端应在 hasMore=true 时提示用户缩小关键词。"],
        appliesTo=["instrument_search", "request_builder"],
        frontendSurfaces=["query_builder", "activity_console"],
    ),
    Disclosure(
        id="large_surface_not_truncated",
        title="大范围 Surface 不自动截断",
        category="limit",
        severity="warning",
        summary="未指定 fixed/listed 边界可能返回很大的 surface；系统保留全部点并发出提示。",
        details=[
            f"超过 {LARGE_SURFACE_POINT_WARNING} 点时生成 LARGE_SURFACE_RESULT activity event。",
            "系统不静默截断；前端应建议缩小日期、expiry 或 strike 范围。",
        ],
        appliesTo=["surface", "request_builder"],
        frontendSurfaces=["query_builder", "activity_console", "quality_panel"],
    ),
    Disclosure(
        id="instrument_catalog_scope",
        title="Instrument catalogue 范围",
        category="limit",
        severity="info",
        summary="当前 volatility 工具只开放 equity instrument catalogue。",
        details=["Swaption 和 Quant Vault 不属于当前 equity implied-volatility 页面范围。"],
        appliesTo=["instrument_search", "request_builder"],
        frontendSurfaces=["query_builder", "methodology"],
    ),
    Disclosure(
        id="health_connectivity_beacon",
        title="Health connectivity 口径",
        category="assumption",
        severity="info",
        summary="Ready check 只读取最近一次 live Cortex 成功或连接/认证失败状态，不主动获取 token。",
        details=[
            "尚未发生 live 请求时 connected 为 null。",
            "NO_DATA、坐标缺失或 schema/parse 错误不等同网络不可达，不会覆盖 connectivity beacon。",
        ],
        appliesTo=["health", "upstream_fetch"],
        frontendSurfaces=["activity_console", "methodology"],
    ),
)


def disclosure_payload() -> list[dict]:
    return [entry.model_dump(mode="json") for entry in DISCLOSURES]
