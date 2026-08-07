"""Gate D contracts for the offline Web MVP."""

from __future__ import annotations

import re

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
    assert 'src="/static/compare-builder.js?v=' in html
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


def test_compare_is_an_indicator_builder_with_internal_bnp_wire_defaults():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert "Indicator builder" in html
    assert "添加并加载指标" in html
    assert "刷新激活项" in html
    assert 'volatilityConvention: "bsVol"' in javascript
    assert 'layout: "matrix"' in javascript
    assert "requestSystemFields" in javascript
    assert "data-indicator-toggle" in javascript
    assert "data-indicator-delete" in javascript
    assert "connectgaps: false" in javascript

def test_compare_listed_coordinates_are_direct_and_exact():
    with TestClient(app) as client:
        javascript = client.get("/static/compare-builder.js").text

    assert "Listed expiry" in javascript
    assert "Observation date" in javascript
    assert "Select listed expiry" in javascript
    assert 'maturity_rule: "listed"' in javascript
    assert 'strike_rule: "fixed"' in javascript
    assert "可直接输入任意正数，也可从下拉建议选择" in javascript

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


def test_compare_supports_eight_synchronized_charts_and_per_indicator_instruments():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert 'id="addChartButton"' in html
    assert "MAX_CHARTS = 8" in javascript
    assert 'instrumentCode: document.getElementById("instrumentCode")' in javascript
    assert 'data-draft="instrumentCode"' in html
    assert 'id="draftChartLane"' in html
    assert "data-indicator-lane" in javascript
    assert 'hovermode: "x unified"' in javascript
    assert "Plotly.Fx.hover" in javascript
    assert "syncXZoom" in javascript

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


def test_query_rail_uses_unnumbered_date_underlying_indicator_groups():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert "1 · 日期范围" not in html
    assert "2 · Underlying 与坐标" not in html
    assert "3 · Indicator builder" not in html
    assert html.index("Range mode") < html.index("Underlying · instrument code") < html.index("Indicator builder")
    assert html.count('id="instrumentCode"') == 1
    assert 'id="slidingWindow"' in html
    assert "52d, 2w, 3m, 3y" in html
    assert "renderScopeFields" in javascript

def test_instrument_search_results_are_clickable_not_a_datalist():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/app.js").text

    # A datalist filters options against the typed text, so searching "9998" would hide a
    # match whose code is "HK_9998". Results are rendered as an explicit list instead.
    # Other datalists stay: for RV windows and tenors the typed text really is the value.
    assert 'id="instrumentOptions"' not in html
    assert 'list="instrumentOptions"' not in html
    assert 'id="instrumentResults"' in html

    assert "function renderInstrumentResults" in javascript
    assert "data-instrument-code" in javascript
    select = javascript.split("function selectInstrument", 1)[1].split("\n}", 1)[0]
    # Picking a result must look exactly like a manual edit to every other listener.
    assert 'input.dispatchEvent(new Event("input", { bubbles: true }))' in select
    assert 'input.dispatchEvent(new Event("change", { bubbles: true }))' in select


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


def test_saved_indicators_can_be_edited_and_duplicated():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert 'id="cancelEditButton"' in html
    assert 'id="builderModeNote"' in html
    assert "data-indicator-edit" in javascript
    assert "data-indicator-duplicate" in javascript
    assert "function startEditing" in javascript
    assert "function duplicateIndicator" in javascript
    # Saving an edit rewrites the item in place and re-requests it.
    apply_edit = javascript.split("function applyIndicatorEdit", 1)[1].split("function startEditing", 1)[0]
    assert "item.config = structuredClone(indicatorState.draft)" in apply_edit
    assert "item.response = null" in apply_edit
    # Editing a derived indicator must not be able to build a reference cycle.
    assert "function dependencyClosure" in javascript
    assert "function operandCandidates" in javascript
    assert "运算指标不能引用自己" in javascript


def test_provider_name_is_not_shown_in_the_interface():
    """Everything the browser renders stays vendor-neutral; only wire values keep bnpp."""
    with TestClient(app) as client:
        pages = {
            "index": client.get("/").text,
            "app.js": client.get("/static/app.js").text,
            "compare-builder.js": client.get("/static/compare-builder.js").text,
            "capabilities": client.get("/api/v1/capabilities").text,
        }
    for name, body in pages.items():
        assert "BNP" not in body, name

    # The lowercase wire enum and the credential env vars are unaffected.
    assert '"bnpp"' in pages["compare-builder.js"]
    assert "code_type" in pages["app.js"]


def test_date_range_supports_sliding_windows_and_fixed_dates():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert 'id="dateMode"' in html
    assert 'id="slidingWindow"' in html
    assert '<option value="sliding">' in html and '<option value="fixed">' in html

    windows = javascript.split("const SLIDING_WINDOWS = [", 1)[1].split("];", 1)[0]
    for window in ("1M", "3M", "6M", "YTD", "1Y", "2Y", "3Y", "5Y", "10Y"):
        assert f'id: "{window}"' in windows

    span = javascript.split("function slidingRange", 1)[1].split("// Writes today's window", 1)[0]
    # The window is measured back from today, so the end date follows the calendar.
    assert "isoDate(new Date())" in span
    assert "end: today" in span

    # Reopening a board re-derives a sliding range instead of replaying stored dates.
    open_board = javascript.split("function openBoard", 1)[1].split("function renderBoards", 1)[0]
    assert "syncSlidingRange()" in open_board
    assert "indicatorState.dateMode = board.dateMode" in open_board
    # A manual refresh catches the day rolling over on a long-lived tab.
    refresh = javascript.split("async function refreshActiveIndicators", 1)[1].split("function invalidateIndicators", 1)[0]
    assert "syncSlidingRange()" in refresh

    # Workspaces and boards saved before sliding ranges existed keep their explicit dates.
    assert 'stored.scope?.dateMode === "sliding" ? "sliding" : "fixed"' in javascript
    assert 'board.dateMode === "sliding" ? "sliding" : "fixed"' in javascript


def test_boards_live_in_the_topbar_not_the_query_rail():
    with TestClient(app) as client:
        html = client.get("/").text

    header = html.split("<header", 1)[1].split("</header>", 1)[0]
    rail = html.split('class="query-rail"', 1)[1].split("</aside>", 1)[0]
    for element in ("boardSelect", "boardName", "saveBoardAsButton", "loadBoardButton"):
        assert f'id="{element}"' in header, element
        assert f'id="{element}"' not in rail, element


def test_boards_reload_saved_indicator_sets_with_fresh_data():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    for element in ("boardSelect", "boardName", "saveBoardAsButton", "updateBoardButton",
                    "deleteBoardButton", "loadBoardButton", "activeBoardLabel"):
        assert f'id="{element}"' in html
    assert 'BOARD_STORAGE_KEY = "volcurve.compare.boards.v1"' in javascript

    open_board = javascript.split("function openBoard", 1)[1].split("function renderBoards", 1)[0]
    # A board restores configuration only, then re-requests every active indicator.
    assert "refreshActiveIndicators()" in open_board
    assert 'status: item.type === "derived" ? "ready" : "stale"' in open_board
    assert "response: null" in open_board
    snapshot = javascript.split("function currentBoardSnapshot", 1)[1].split("// Board feedback", 1)[0]
    assert "serializeItem" in snapshot
    assert "startDate" in snapshot and "chartCount" in snapshot
    # Column widths travel with the board, so reopening one restores its table layout.
    assert "columnWidths: { ...indicatorState.columnWidths }" in snapshot
    assert "indicatorState.columnWidths = { ...board.columnWidths }" in javascript


def test_unsaved_board_changes_are_flagged_before_they_can_be_lost():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert 'id="boardDirtyMark"' in html
    assert 'id="boardUnsavedNote"' in html

    signature = javascript.split("function boardSignature", 1)[1].split("function stableStringify", 1)[0]
    # A sliding board's dates come from today, so they must not read as an edit.
    assert 'startDate: sliding ? null : snapshot.startDate' in signature
    assert 'slidingWindow: sliding ? snapshot.slidingWindow : null' in signature
    assert "columnWidths" in signature and "chartCount" in signature
    # Key order must not matter: a config rebuilt in another order is not a change.
    assert "Object.keys(value).sort()" in javascript

    # Loading over unsaved work needs a second, deliberate click.
    assert "function openingBoardWouldDiscardWork" in javascript
    assert "indicatorState.pendingBoardLoad = board.id" in javascript
    assert "再点一次「载入」确认" in javascript
    # Every mutation persists, so that is where the marker is refreshed.
    persist = javascript.split("function persistWorkspace", 1)[1].split("function serializeItem", 1)[0]
    assert "renderBoardState()" in persist


def test_a_switched_off_indicator_is_still_loaded_when_a_derived_one_reads_it():
    with TestClient(app) as client:
        javascript = client.get("/static/compare-builder.js").text

    assert "function itemsNeedingData" in javascript
    needed = javascript.split("function itemsNeedingData", 1)[1].split("function isNeededButHidden", 1)[0]
    # Start from what is displayed, then pull in operands transitively.
    assert "item.config.operandA, item.config.operandB" in needed

    # The fetch guard must not refuse an inactive indicator any more.
    fetch = javascript.split("async function fetchIndicator", 1)[1].split("async function refreshActiveIndicators", 1)[0]
    assert "if (!item.active" not in fetch
    assert "itemsNeedingData().filter" in javascript
    # Turning a derived indicator on, adding one, or editing its operands can all pull in
    # something that was never loaded.
    assert javascript.count("fetchMissingDependencies()") >= 4
    assert "供运算指标使用" in javascript


def test_long_indicator_names_are_shown_in_full():
    with TestClient(app) as client:
        stylesheet = client.get("/static/styles.css").text

    # Names identify the indicator, so they wrap rather than being cut off with an ellipsis.
    for rule in (".saved-indicator-copy strong", ".stats-series-name", ".stats-row-name"):
        declaration = stylesheet.split(rule + " {", 1)[1].split("}", 1)[0]
        assert "text-overflow: ellipsis" not in declaration, rule
        assert "overflow-wrap: anywhere" in declaration, rule
    # Numeric cells stay clipped; only headers grow.
    assert ".stats-table td { overflow: hidden; text-overflow: ellipsis; }" in stylesheet


def test_indicator_columns_can_be_renamed_to_a_personal_alias():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert "双击 indicator 列头可以给它起一个自己的别名" in html
    assert "data-indicator-alias" in javascript
    assert "function startIndicatorAliasEdit" in javascript

    setter = javascript.split("function setIndicatorAlias", 1)[1].split("function startIndicatorAliasEdit", 1)[0]
    # Blank or unchanged text clears the alias instead of storing a literal rename.
    assert 'item.config.alias = trimmed && trimmed !== indicatorTechnicalLabel(item) ? trimmed : ""' in setter
    assert "persistWorkspace()" in setter

    # The alias lives in the indicator's own config, so it travels with boards too.
    assert 'alias: "",' in javascript.split("function defaultDraft", 1)[1].split("}", 1)[0] + '"'
    # The generated name is never overwritten and stays reachable.
    assert "function indicatorTechnicalLabel" in javascript
    label = javascript.split("function indicatorLabel", 1)[1].split("function indicatorTechnicalLabel", 1)[0]
    assert "indicatorAlias(item) || indicatorTechnicalLabel(item, depth)" in label
    # Statistic rows are back to their fixed names.
    assert "startStatAliasEdit" not in javascript


def test_unsaved_board_changes_are_signalled_in_red():
    with TestClient(app) as client:
        stylesheet = client.get("/static/styles.css").text

    dot = stylesheet.split(".board-menu summary span.board-dirty-mark {", 1)[1].split("}", 1)[0]
    assert "border-radius: 50%" in dot and "display: inline-block" in dot
    assert "#ff5f56" in dot
    # The same red continues inside the menu, on the note and on the button that fixes it.
    assert ".board-menu-actions .secondary-button.is-emphasised { color: #fff; background: var(--red)" in stylesheet
    note = stylesheet.split("p.board-unsaved-note {", 1)[1].split("}", 1)[0]
    assert "#93261c" in note


def test_statistics_table_is_transposed_with_resizable_columns():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert 'id="indicatorStatsCols"' in html
    assert 'id="indicatorStatsTable"' in html
    assert "每列是一个 indicator，每行是一个统计项" in html

    render = javascript.split("function renderIndicatorStats", 1)[1].split("function resizeHandle", 1)[0]
    # Body rows are statistics; each series contributes a column.
    assert "rows.map((column)" in render
    assert "series.map(({ item, stats }) => statCell(column, item, stats))" in render
    assert "applyStatsTableWidth()" in render

    resize = javascript.split("function startColumnResize", 1)[1].split("// Columns (indicators)", 1)[0]
    assert "MIN_COLUMN_WIDTH" in resize
    # The <col> has no usable box of its own, so the header cell is measured instead.
    assert "headerCell.getBoundingClientRect().width" in resize
    assert "persistWorkspace()" in resize


def test_statistics_label_column_stays_pinned_while_scrolling_sideways():
    with TestClient(app) as client:
        stylesheet = client.get("/static/styles.css").text

    # Browsers ignore position:sticky on cells of a collapsed-border table, and the
    # pinning rule has to outrank the relative positioning the resize handles need.
    assert "border-collapse: separate" in stylesheet
    assert ".stats-table .stats-label-cell { position: sticky; left: 0;" in stylesheet
    assert ".stats-table th { position: relative; }" in stylesheet
    assert stylesheet.index(".stats-table th { position: relative; }") < stylesheet.index(
        ".stats-table .stats-label-cell { position: sticky"
    )


def test_statistics_rows_and_columns_can_be_dragged_into_a_new_order():
    with TestClient(app) as client:
        javascript = client.get("/static/compare-builder.js").text

    assert 'data-drag-column="${item.id}"' in javascript
    assert 'data-drag-row="${escapeHtml(column.id)}"' in javascript
    assert "function bindStatsDragControls" in javascript

    drag = javascript.split("function bindStatsDragControls", 1)[1].split("function statsDropTarget", 1)[0]
    # A width drag must never be mistaken for a reorder.
    assert 'document.body.classList.contains("is-resizing-column")' in drag

    reorder = javascript.split("function applyStatsReorder", 1)[1].split("function moveWithin", 1)[0]
    # Reordering a column reorders the indicators themselves so charts stay in step.
    assert "moveWithin(indicatorState.items, from, to)" in reorder
    assert "moveWithin(columns, from, to)" in reorder
    assert "persistStatsColumns()" in reorder


def test_statistics_columns_are_configurable_and_cover_the_full_metric_set():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert 'id="statsColumnList"' in html
    assert 'id="statsColumnsResetButton"' in html
    assert 'STATS_STORAGE_KEY = "volcurve.compare.statscolumns.v1"' in javascript

    columns = javascript.split("const STAT_COLUMNS = [", 1)[1].split("];", 1)[0]
    for metric in ("zScore", "change5", "change20", "change60", "iqr", "maxDate", "minDate",
                   "largestGain", "largestDrop", "skewness", "kurtosis", "mean20", "mean60",
                   "autocorrelation", "autocorrelation5", "autocorrelation20", "percentile",
                   "range", "p25", "p75", "vsMean20", "meanAbsChange", "positiveShare",
                   "sessionsSinceMax", "sessionsSinceMin"):
        assert f'id: "{metric}"' in columns

    restore = javascript.split("function restoreStatsColumns", 1)[1].split("function persistStatsColumns", 1)[0]
    # Columns added in a later release must not disappear for users with a saved layout.
    assert "if (!seen.has(column.id)) ordered.push({ id: column.id, visible: column.defaultVisible !== false })" in restore

    # Longer-window and secondary statistics default to hidden, one click away.
    hidden_by_default = ("change60", "mean60", "vsMean20", "p25", "p75", "sessionsSinceMax",
                          "sessionsSinceMin", "meanAbsChange", "positiveShare",
                          "autocorrelation5", "autocorrelation20")
    for metric in hidden_by_default:
        assert f'id: "{metric}", label:' in columns and "defaultVisible: false" in columns.split(f'id: "{metric}",', 1)[1].split("\n", 1)[0]
    # The everyday statistics stay on by default.
    for metric in ("change1", "change5", "change20", "mean", "mean20", "median",
                   "stdDev", "percentile", "zScore", "skewness", "kurtosis", "autocorrelation"):
        line = columns.split(f'id: "{metric}",', 1)[1].split("\n", 1)[0]
        assert "defaultVisible: false" not in line

    # Volatility renders at one decimal; percentile and z-score share a colour scale.
    digits = javascript.split("function valueDigits", 1)[1].split("function percentileBucket", 1)[0]
    assert 'if (unit === "vol") return 1;' in digits
    assert "function percentileBucket" in javascript
    assert "function zScoreBucket" in javascript
    assert "heat-high" in javascript and "heat-low" in javascript


def test_statistics_table_summarizes_every_displayed_indicator():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    assert 'id="indicatorStatsBody"' in html
    assert 'id="indicatorStatsHead"' in html
    assert "renderIndicatorStats" in javascript
    columns = javascript.split("const STAT_COLUMNS = [", 1)[1].split("];", 1)[0]
    for column in ("观测数", "最新值", "最小", "最大", "平均", "中位数", "标准差", "最新值百分位"):
        assert column in columns
    summarize = javascript.split("function summarizeSeries", 1)[1]
    # Statistics skip missing points instead of filling them in.
    assert "point.value !== null && point.value !== undefined" in summarize
    assert "sorted.filter((value) => value <= latest.value).length / count" in summarize


def test_a_narrower_range_is_reused_and_a_force_refresh_can_bypass_it():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    # Asking for a sub-range of something already stored used to force a fresh read purely
    # by accident; now that it is reused, there has to be a deliberate way past the cache.
    assert 'id="forceRefreshIndicatorsButton"' in html
    assert "强制刷新" in html
    assert "function forceRefreshActiveIndicators" in javascript
    assert 'refreshActiveIndicators({ force: true })' in javascript

    fetch = javascript.split("async function fetchIndicator", 1)[1].split(
        "async function refreshActiveIndicators", 1
    )[0]
    assert "force ? { ...item.request, forceRefresh: true } : item.request" in fetch
    # The flag belongs to the one call, not to the indicator that gets saved to a board.
    assert "forceRefresh" not in javascript.split("function buildIndicatorRequest", 1)[1].split(
        "function coordinateRequest", 1
    )[0]


def test_several_indicators_can_be_repointed_at_another_underlying_at_once():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    for control in ("bulkModeButton", "bulkInstrumentCode", "bulkMoveButton", "bulkCopyButton"):
        assert f'id="{control}"' in html, control
    assert "换成此标的" in html and "复制为此标的" in html

    # Changing one operand at a time leaves a combination straddling two underlyings, so a
    # selected combination brings its whole operand tree with it.
    closure = javascript.split("function bulkTargetIds", 1)[1].split("function setBulkSelection", 1)[0]
    assert "item.config.operandA, item.config.operandB" in closure
    # Operands pulled in this way are shown ticked and locked rather than changed silently.
    box = javascript.split("const bulkBox =", 1)[1].split("return `<article", 1)[0]
    assert "locked ? \"is-locked\"" in box and 'locked ? "disabled" : ""' in box

    # The selection is transient; it must never reach localStorage.
    persist = javascript.split("function persistWorkspace", 1)[1].split("function ", 1)[0]
    assert "bulkSelection" not in persist and "bulkMode" not in persist


def test_copying_a_combination_to_another_underlying_rewires_it_to_the_copies():
    with TestClient(app) as client:
        javascript = client.get("/static/compare-builder.js").text

    copy = javascript.split("function bulkCopy", 1)[1].split("function duplicateWarning", 1)[0]
    # Without the id map the copied combination stays pointed at the original operands and
    # silently reproduces the cross-underlying mix the feature exists to prevent.
    assert "idMap.set(source.id, copy.id)" in copy
    assert 'for (const key of ["operandA", "operandB"])' in copy
    assert "idMap.get(Number(copy.config[key]))" in copy
    # A copy carrying the source's alias would be indistinguishable from it.
    assert 'copy.config.alias = ""' in copy
    assert 'if (copy.type !== "derived") copy.config.instrumentCode = code;' in copy

    move = javascript.split("function bulkMove", 1)[1].split("function bulkCopy", 1)[0]
    # A move keeps the card's own name but says so, since the name may no longer fit.
    assert "保留了原有别名" in move
    assert "item.response = null" in move


def test_the_page_can_never_be_assembled_from_mismatched_asset_versions():
    """A stale script beside fresh markup breaks in ways that look like ordinary bugs."""
    with TestClient(app) as client:
        page = client.get("/")
        html = page.content.decode("utf-8")

    # The static mount hands out ETag/Last-Modified, so a browser will happily keep a script
    # cached. Stamping the URL makes each version a distinct resource instead.
    stamped = re.findall(r'/static/(app\.js|compare-builder\.js|styles\.css)\?v=([^"]+)', html)
    assert {name for name, _ in stamped} == {"app.js", "compare-builder.js", "styles.css"}
    assert len({version for _, version in stamped}) == 1, "all assets must carry one version"
    assert "{{ASSET_VERSION}}" not in html, "the placeholder must be substituted"

    # The HTML is the only thing carrying the current version, so it must always revalidate.
    assert "no-cache" in page.headers.get("cache-control", "")


def test_one_missing_control_does_not_disable_the_rest_of_the_page():
    with TestClient(app) as client:
        javascript = client.get("/static/compare-builder.js").text

    # Binding used to be an unguarded sequence: a null element threw and silently abandoned
    # every binding after it, so a missing button cost you the date range and the boards too.
    assert "function on(id, event, handler)" in javascript
    init = javascript.split("function initIndicatorBuilder", 1)[1].split("function bindDateModeControls", 1)[0]
    assert "$(" not in init, "every binding in init must go through the guarded helper"
    assert "console.error(`volcurve: 「${name}」初始化失败`" in init


def test_local_async_errors_render_backend_suggested_action():
    with TestClient(app) as client:
        app_javascript = client.get("/static/app.js").text
        compare_javascript = client.get("/static/compare-builder.js").text
        playground = client.get("/static/cortex-playground.js").text

    assert "apiErrorSummary" in app_javascript
    assert "suggestedAction" in app_javascript
    assert "apiErrorSummary" in compare_javascript
    assert "strikeSuggestedAction" in compare_javascript
    assert "suggestedActionSource" in compare_javascript
    assert "action ${data.suggestedActionSource}" in playground
