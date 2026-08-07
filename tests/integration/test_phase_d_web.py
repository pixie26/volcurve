"""Gate D contracts for the offline Web MVP."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.disclosures import DISCLOSURES
from app.main import app


def test_web_workspace_and_offline_assets_are_served():
    with TestClient(app) as client:
        page = client.get("/")
        javascript = client.get("/static/app.js")
        compare_builder = client.get("/static/compare-builder.js")
        stylesheet = client.get("/static/styles.css")
        plotly = client.get("/static/vendor/plotly-5.24.1.min.js")

    html = page.content.decode("utf-8")
    assert page.status_code == 200
    assert 'lang="zh-Hans"' in html
    assert "动态" not in html  # UI wording stays user-facing, not implementation-facing.
    assert "Compare 用于一个精确坐标" in html
    assert "未复权" in html
    assert 'src="/static/vendor/plotly-5.24.1.min.js"' in html
    assert 'src="/static/compare-builder.js"' in html
    assert 'id="indicatorCharts"' in html
    assert 'id="savedIndicators"' in html
    assert "https://" not in html
    assert javascript.status_code == 200
    assert compare_builder.status_code == 200
    assert stylesheet.status_code == 200
    assert plotly.status_code == 200
    assert len(plotly.content) > 1_000_000


def test_web_discovers_backend_modes_and_renders_all_required_disclosure_surfaces():
    with TestClient(app) as client:
        capabilities = client.get("/api/v1/capabilities").json()
        javascript = client.get("/static/app.js").text

    assert all(mode["enabled"] for mode in capabilities["requestModes"])
    assert "state.capabilities.requestModes" in javascript
    assert "state.capabilities.moneynessLevels" in javascript
    assert "state.capabilities.deltaStrikes" in javascript
    assert {"smile", "term_structure"}.issubset(capabilities["indicators"])

    supported_surfaces = {
        "query_builder",
        "methodology",
        "quality_panel",
        "activity_console",
    }
    assert all(disclosure.frontendRequired for disclosure in DISCLOSURES)
    assert all(set(disclosure.frontendSurfaces) <= supported_surfaces for disclosure in DISCLOSURES)
    for surface in supported_surfaces:
        assert surface in javascript


def test_web_keeps_missing_coordinates_and_arbitrary_rv_windows_explicit():
    with TestClient(app) as client:
        javascript = client.get("/static/app.js").text

    assert "不会自动换成邻近 strike 或 expiry" in javascript
    assert "最近返回 strike" in javascript
    assert "最近返回 expiry" in javascript
    assert "不会自动取最近档位" in javascript
    assert "Number.isInteger(window)" in javascript
    assert "connectgaps: false" in javascript


def test_web_discovers_listed_contract_coordinates_without_auto_substitution():
    with TestClient(app) as client:
        javascript = client.get("/static/app.js").text

    assert "加载可用坐标" in javascript
    assert 'maturity_rule: "fixed"' in javascript
    assert 'strike_rule: "fixed"' in javascript
    discovery_function = javascript.split("async function loadListedCoordinates", 1)[1].split(
        "function renderAvailableStrikes", 1
    )[0]
    assert "low_fixed_strike" not in discovery_function
    assert "系统未自动选择 strike" in javascript
    assert "这是用户选择，不是最近坐标替代" in javascript


def test_compare_is_an_indicator_builder_with_visible_bnp_request_fields():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert "Indicator builder" in html
    assert "添加并加载指标" in html
    assert "刷新激活项" in html
    assert "Vol convention" in javascript
    assert "Layout" in javascript
    assert 'volatilityConvention: "bsVol"' in javascript
    assert 'layout: "matrix"' in javascript
    assert "data-indicator-toggle" in javascript
    assert "data-indicator-delete" in javascript
    assert "connectgaps: false" in javascript


def test_compare_manual_coordinates_distinguish_schema_rejection_from_missing_data():
    with TestClient(app) as client:
        javascript = client.get("/static/compare-builder.js").text

    assert "BNP OpenAPI 不接受 sliding maturity" in javascript
    assert "BNP OpenAPI 不接受 moneyness" in javascript
    assert "BNP API 不支持 Sliding maturity + Absolute strike" in javascript
    assert "允许手输任意合法日期" in javascript
    assert "不存在的精确 strike 返回缺失" in javascript
    assert "加载可用坐标" in javascript
    assert "系统没有自动选择" in javascript


def test_compare_non_iv_carrier_assumptions_are_visible():
    with TestClient(app) as client:
        javascript = client.get("/static/compare-builder.js").text

    assert "3M K/F 100%" in javascript
    assert "该坐标不进入 RV 公式" in javascript
    assert "reference 3M K/F 100%" in javascript
    assert "K/F 100% response carrier" in javascript


def test_compare_restores_full_per_indicator_details_and_persists_configuration():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text
        app_javascript = client.get("/static/app.js").text

    assert 'id="detailIndicatorSelect"' in html
    assert "行情响应不保存，重新打开后会重新请求" in html
    assert "localStorage.setItem(STORAGE_KEY" in javascript
    assert "localStorage.getItem(STORAGE_KEY" in javascript
    assert "normalizeStoredConfig" in javascript
    assert "renderIndicatorDetailTable" in javascript
    assert "renderIndicatorDetailMethodology" in javascript
    assert "renderIndicatorDetailQuality" in javascript
    assert "renderIndicatorDetailActivity" in javascript
    assert "renderIndicatorDetailDisclosures" in javascript
    assert "BROWSER_RENDER_READY" in javascript
    assert "data-indicator-detail" in javascript
    assert "volcurveCompareDetails.downloadSelectedCsv" in app_javascript


def test_compare_supports_five_synchronized_charts_and_per_indicator_instruments():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert "最多 5 个坐标" in html
    assert 'id="addChartButton"' in html
    assert "MAX_CHARTS = 5" in javascript
    assert 'instrumentCode: document.getElementById("instrumentCode")' in javascript
    assert 'data-draft="instrumentCode"' in javascript
    assert 'data-draft="chartLane"' in javascript
    assert "data-indicator-lane" in javascript
    assert 'dragmode: "zoom"' in javascript
    assert 'hovermode: "x unified"' in javascript
    assert "Plotly.Fx.hover" in javascript
    assert "Plotly.Fx.unhover" in javascript
    assert "syncXZoom" in javascript
    assert 'update["xaxis.range[0]"]' in javascript


def test_hovering_one_chart_reads_out_every_chart_for_that_date():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert 'id="crosshairReadout"' in html
    assert "renderCrosshairReadout" in javascript
    # The readout walks every lane, not just the hovered one.
    readout = javascript.split("function renderCrosshairReadout", 1)[1].split("function renderIndicatorDetails", 1)[0]
    assert "lane <= indicatorState.chartCount" in readout
    assert "坐标 ${lane}" in readout
    assert "HOVER DATE" in readout


def test_hover_draws_the_same_vertical_guide_line_on_every_chart():
    with TestClient(app) as client:
        javascript = client.get("/static/compare-builder.js").text

    # Spikes snap to the observation date so every lane's line sits on one vertical.
    assert 'spikesnap: "data"' in javascript
    assert 'spikedash: "dot"' in javascript
    assert 'spikemode: "across"' in javascript

    sync = javascript.split("function syncHover", 1)[1].split("function axisTimestamp", 1)[0]
    # Plotly only renders spike lines for the numeric {xval} form of Fx.hover.
    assert "Plotly.Fx.hover(div, { xval }, laneSubplot(div))" in sync
    assert "pointNumber" not in sync
    # The re-entrancy guard must not outlive the synchronous fan-out, otherwise a
    # source unhover cancels the hover that immediately follows it.
    assert "setTimeout" not in sync
    assert "finally" in sync

    lane_subplot = javascript.split("function laneSubplot", 1)[1].split("\n  }", 1)[0]
    assert '"xy" : "xy2"' in lane_subplot


def test_query_rail_asks_for_dates_then_underlying_then_indicator_once():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert html.index("1 · 日期范围") < html.index("2 · Underlying 与坐标") < html.index("3 · Indicator builder")
    # A single underlying input drives both the surface query and every new indicator.
    assert html.count('list="instrumentOptions"') == 1
    assert 'data-draft="instrumentCode"' in html
    assert 'id="draftChartLane"' in html
    assert 'data-draft="chartLane"' in html
    assert "indicatorPlacementFields" not in javascript
    assert "renderScopeFields" in javascript


def test_saved_indicators_can_be_combined_with_arithmetic_operators():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert 'value="derived"' in html
    assert "OPERATOR_SYMBOLS = { add:" in javascript
    assert "computeDerivedSeries" in javascript
    assert 'data-draft="operandA"' in javascript
    assert 'data-draft="operandB"' in javascript
    # Derived series stay explicit about gaps and never divide by zero.
    operator = javascript.split("function applyOperator", 1)[1].split("function numericValue", 1)[0]
    assert "if (left === null || right === null) return null;" in operator
    assert "if (right === 0) return null;" in operator
    assert "指标运算的引用形成了循环" in javascript
    assert "两个操作数在当前日期范围内没有共同观察日" in javascript
    assert "请先删除这些运算指标" in javascript


def test_statistics_table_summarizes_every_displayed_indicator():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert 'id="indicatorStatsBody"' in html
    assert 'id="indicatorStatsHead"' in html
    assert "renderIndicatorStats" in javascript
    statistics = javascript.split("function renderIndicatorStats", 1)[1].split("function summarizeSeries", 1)[0]
    for column in ("观测数", "最新值", "最小", "最大", "平均", "中位数", "标准差", "最新值百分位"):
        assert column in statistics
    summarize = javascript.split("function summarizeSeries", 1)[1]
    # Statistics skip missing points instead of filling them in.
    assert "point.value !== null && point.value !== undefined" in summarize
    assert "sorted.filter((value) => value <= latest.value).length / count" in summarize
