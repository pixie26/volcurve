"use strict";

const state = {
  capabilities: null,
  queryKind: "compare",
  lastRequest: null,
  lastResponse: null,
  contractDiscovery: null,
};

const MODE_LABELS = {
  sliding_moneyness: "Sliding · moneyness",
  sliding_delta: "Sliding · delta",
  fixed_strike: "Fixed/Listed · absolute strike",
  listed_moneyness: "Fixed/Listed · moneyness",
};

const INDICATOR_LABELS = {
  implied_vol: "Implied vol",
  realized_vol: "Realized vol",
  spot: "Spot",
  forward: "Forward",
  iv_minus_rv: "IV − RV",
  iv_divided_by_rv: "IV / RV",
  percentile: "Spread percentile",
  zscore: "Spread z-score",
  correlation: "IV/RV correlation",
  smile: "Smile",
  term_structure: "Term structure",
};

const DEFAULT_INDICATORS = new Set([
  "implied_vol",
  "realized_vol",
  "spot",
  "forward",
  "iv_minus_rv",
  "smile",
  "term_structure",
]);

const FRONTEND_SURFACE_IDS = {
  query_builder: "queryBuilderDisclosures",
  methodology: "methodologyDisclosures",
  quality_panel: "qualityDisclosures",
  activity_console: "activityDisclosures",
};

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

function isoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addCalendar(dateString, { years = 0, months = 0, days = 0 }) {
  const [year, month, day] = dateString.split("-").map(Number);
  const result = new Date(year + years, month - 1 + months, day + days);
  return isoDate(result);
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  return new Intl.NumberFormat("zh-HK", { maximumFractionDigits: digits }).format(value);
}

function formatPercent(value, digits = 2) {
  return value === null || value === undefined ? "—" : `${formatNumber(value, digits)}%`;
}

function selectedIndicators() {
  return new Set(
    [...document.querySelectorAll("#indicatorSelector input:checked")].map((input) => input.value),
  );
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    let error = null;
    if (contentType.includes("application/json")) error = await response.json();
    throw Object.assign(new Error(error?.message || `HTTP ${response.status}`), {
      payload: error,
      status: response.status,
      requestId: response.headers.get("x-request-id"),
    });
  }
  return response;
}

function apiErrorSummary(error, fallback = "请求失败") {
  const payload = error?.payload || {};
  const parts = [];
  if (payload.code) parts.push(payload.code);
  parts.push(payload.message || error?.message || fallback);
  if (payload.suggestedAction) parts.push(`建议：${payload.suggestedAction}`);
  if (payload.requestId) parts.push(`Request ${payload.requestId}`);
  return parts.filter(Boolean).join(" · ");
}

function apiErrorMeta(error, fallback = "请求失败") {
  const payload = error?.payload || {};
  return {
    message: payload.message || error?.message || fallback,
    errorCode: payload.code || null,
    suggestedAction: payload.suggestedAction || null,
    suggestedActionSource: payload.suggestedActionSource || null,
    requestId: payload.requestId || error?.requestId || null,
    stage: payload.stage || null,
  };
}

async function initialize() {
  const today = new Date();
  $("endDate").value = isoDate(today);
  $("startDate").value = isoDate(new Date(today.getFullYear() - 1, today.getMonth(), today.getDate()));
  bindEvents();
  await Promise.all([loadCapabilities(), loadHealth()]);
}

function bindEvents() {
  $("queryForm").addEventListener("submit", runQuery);
  $("requestMode").addEventListener("change", () => {
    state.contractDiscovery = null;
    renderCoordinateFields();
  });
  $("maturityRule").addEventListener("change", renderCoordinateFields);
  $("strikeRule").addEventListener("change", renderCoordinateFields);
  $("instrumentCode").addEventListener("input", resetContractDiscovery);
  $("endDate").addEventListener("change", resetContractDiscovery);
  $("instrumentSearchButton").addEventListener("click", searchInstruments);
  $("instrumentCode").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      // The field sits inside the query form; searching must not submit it.
      event.preventDefault();
      searchInstruments();
    } else if (event.key === "Escape") {
      hideInstrumentResults();
    }
  });
  $("instrumentResults").addEventListener("click", (event) => {
    const choice = event.target.closest("[data-instrument-code]");
    if (choice) selectInstrument(choice.dataset.instrumentCode);
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest("#instrumentResults, #instrumentCode, #instrumentSearchButton")) {
      hideInstrumentResults();
    }
  });
  $("snapshotDate").addEventListener("change", renderSurfaceSnapshot);
  $("csvButton").addEventListener("click", downloadCsv);
  document.querySelectorAll('input[name="queryKind"]').forEach((input) => {
    input.addEventListener("change", () => {
      state.queryKind = input.value;
      $("rvSection").classList.toggle("is-hidden", input.value !== "compare");
      renderCoordinateFields();
      renderIndicatorSelector();
      renderBuilderDisclosures();
    });
  });
}

async function loadCapabilities() {
  try {
    const response = await apiFetch("/api/v1/capabilities");
    state.capabilities = await response.json();
    $("apiVersion").textContent = `CORTEX API ${state.capabilities.apiVersion}`;
    const modeSelect = $("requestMode");
    modeSelect.innerHTML = state.capabilities.requestModes
      .filter((mode) => mode.enabled)
      .map((mode) => `<option value="${escapeHtml(mode.id)}">${escapeHtml(MODE_LABELS[mode.id] || mode.id)}</option>`)
      .join("");
    $("rvWindowOptions").innerHTML = state.capabilities.rvWindows
      .map((window) => `<option value="${window}"></option>`)
      .join("");
    const minimum = state.capabilities.rvWindowRange.minimum;
    $("rvWindow").min = String(minimum);
    $("rvWindowHelp").textContent = `快捷档位仅用于输入建议；接受任意 ≥ ${minimum} 的整数，不取最近值。`;
    renderCoordinateFields();
    renderIndicatorSelector();
    renderBuilderDisclosures();
    window.dispatchEvent(new CustomEvent("volcurve:capabilities"));
  } catch (error) {
    showError(error, "无法载入 capability registry");
  }
}

async function loadHealth() {
  try {
    const response = await apiFetch("/health/ready");
    const health = await response.json();
    const pill = $("healthStatus");
    pill.className = `status-pill ${health.connected === false ? "status-warning" : "status-ok"}`;
    pill.innerHTML = `<i></i>${health.connected === false ? "Cortex 最近连接失败" : health.connected === true ? "Cortex 已连接" : "服务已就绪"}`;
  } catch (_error) {
    $("healthStatus").className = "status-pill status-warning";
    $("healthStatus").innerHTML = "<i></i>服务状态未知";
  }
}

function renderCoordinateFields() {
  if (!state.capabilities) return;
  const mode = $("requestMode").value || "sliding_moneyness";
  const compare = state.queryKind === "compare";
  const maturityRuleVisible = mode === "fixed_strike" || mode === "listed_moneyness";
  const strikeRuleVisible = mode === "sliding_moneyness" || mode === "listed_moneyness";
  $("maturityRuleRow").classList.toggle("is-hidden", !maturityRuleVisible);
  $("strikeRuleRow").classList.toggle("is-hidden", !strikeRuleVisible);

  let html = "";
  if (mode === "sliding_moneyness") {
    html = coordinateSelects(
      "Moneyness · %",
      "strike",
      state.capabilities.moneynessLevels,
      100,
      "Maturity",
      "maturity",
      state.capabilities.slidingMaturities,
      "3M",
      compare,
    );
  } else if (mode === "sliding_delta") {
    html = coordinateSelects(
      "Put / Call delta",
      "delta",
      state.capabilities.deltaStrikes,
      "p25.0",
      "Maturity",
      "maturity",
      state.capabilities.deltaMaturities,
      "3M",
      compare,
    );
  } else if (mode === "fixed_strike") {
    const expiry = addCalendar($("endDate").value || isoDate(new Date()), { months: 3 });
    const highExpiry = addCalendar(expiry, { months: 3 });
    html = `<div class="coordinate-grid">
      ${numberField(compare ? "Strike" : "Low strike", "lowFixedStrike", "100", "0.000001")}
      ${compare ? "" : numberField("High strike", "highFixedStrike", "120", "0.000001")}
      ${dateField(compare ? "Expiry" : "Low expiry", "lowFixedMaturity", expiry)}
      ${compare ? "" : dateField("High expiry", "highFixedMaturity", highExpiry)}
    </div>${contractDiscoveryPanel()}`;
  } else {
    const expiry = addCalendar($("endDate").value || isoDate(new Date()), { months: 3 });
    const highExpiry = addCalendar(expiry, { months: 3 });
    html = `<div class="coordinate-grid">
      ${selectField(compare ? "Moneyness · %" : "Low moneyness · %", "lowStrike", state.capabilities.moneynessLevels, 100)}
      ${compare ? "" : selectField("High moneyness · %", "highStrike", state.capabilities.moneynessLevels, 110)}
      ${dateField(compare ? "Expiry" : "Low expiry", "lowFixedMaturity", expiry)}
      ${compare ? "" : dateField("High expiry", "highFixedMaturity", highExpiry)}
    </div>`;
  }
  $("coordinateFields").innerHTML = html;
  bindContractDiscoveryEvents();
  $("coordinateModeNote").textContent = compare
    ? "Compare 只请求一个精确坐标。缺失时保持缺失，不会自动换成邻近 strike 或 expiry。"
    : "Surface 保留所选范围内全部返回坐标，不会自动降维；图表只渲染当前日期切片。";
}

function resetContractDiscovery() {
  if (!state.contractDiscovery) return;
  state.contractDiscovery = null;
  if ($("requestMode").value === "fixed_strike") renderCoordinateFields();
}

function contractDiscoveryPanel() {
  const discovery = state.contractDiscovery;
  const observationDate = discovery?.date || $("endDate").value || isoDate(new Date());
  let result = "";
  if (discovery?.status === "loading") {
    result = '<p class="coordinate-discovery-status">正在向数据源请求该观察日的 listed surface…</p>';
  } else if (discovery?.status === "error") {
    const parts = [
      discovery.errorCode,
      discovery.message,
      discovery.suggestedAction ? `建议：${discovery.suggestedAction}` : null,
      discovery.requestId ? `Request ${discovery.requestId}` : null,
    ].filter(Boolean);
    result = `<p class="coordinate-discovery-error">${parts.map(escapeHtml).join(" · ")}</p>`;
  } else if (discovery?.status === "ready") {
    const expiryOptions = discovery.snapshot.maturities
      .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
      .join("");
    result = `<div class="coordinate-grid discovery-selectors">
      <label class="field"><span>Available expiry</span><select id="availableExpiry"><option value="">请选择实际返回 expiry</option>${expiryOptions}</select></label>
      <label class="field"><span>Available strike</span><select id="availableStrike" disabled><option value="">先选择 expiry</option></select></label>
    </div>
    <p id="contractCoordinateStatus" class="coordinate-discovery-status">已返回 ${discovery.snapshot.maturities.length} 个 expiry；请选择一个 expiry 查看具有有效 IV 的 strikes。</p>
    <button id="applyContractCoordinate" class="secondary-button discovery-apply" type="button" disabled>应用所选坐标</button>`;
  }
  return `<section class="coordinate-discovery" aria-label="可用 listed 合约坐标">
    <div class="coordinate-discovery-heading"><div><strong>可用合约坐标</strong><small>按观察日读取实际 listed expiry/strike；数据源将此组合命名为 fixed maturity + fixed strike。不会替代当前输入。</small></div></div>
    <div class="field-grid discovery-loader">
      <label class="field"><span>Observation date</span><input id="contractObservationDate" type="date" value="${escapeHtml(observationDate)}" /></label>
      <button id="loadContractCoordinates" class="secondary-button" type="button" ${discovery?.status === "loading" ? "disabled" : ""}>加载可用坐标</button>
    </div>${result}
  </section>`;
}

function bindContractDiscoveryEvents() {
  const loadButton = $("loadContractCoordinates");
  if (!loadButton) return;
  loadButton.addEventListener("click", loadListedCoordinates);
  const expirySelect = $("availableExpiry");
  if (expirySelect) expirySelect.addEventListener("change", renderAvailableStrikes);
  const strikeSelect = $("availableStrike");
  if (strikeSelect) strikeSelect.addEventListener("change", updateContractApplyState);
  const applyButton = $("applyContractCoordinate");
  if (applyButton) applyButton.addEventListener("click", applyContractCoordinate);
}

async function loadListedCoordinates() {
  const code = $("instrumentCode").value.trim();
  const date = $("contractObservationDate").value;
  if (!code || !date) {
    $("formError").textContent = "加载可用坐标前，请输入 instrument code 和 observation date。";
    $("formError").classList.remove("is-hidden");
    return;
  }
  $("formError").classList.add("is-hidden");
  state.contractDiscovery = { status: "loading", code, date };
  renderCoordinateFields();
  try {
    const response = await apiFetch(state.capabilities.endpoints.surface, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        volatilityRequest: {
          code,
          code_type: "bnpp",
          volatility_convention: "bsVol",
          start_date: date,
          end_date: date,
          maturity_rule: "fixed",
          strike_rule: "fixed",
          layout: "matrix",
        },
      }),
    });
    const payload = await response.json();
    const snapshot = payload.snapshots.find((item) => item.date === date);
    if (!snapshot) throw new Error("数据源在该观察日没有返回 listed surface。请改用另一个可用市场日期。");
    state.contractDiscovery = { status: "ready", code, date, snapshot, requestId: payload.requestId };
  } catch (error) {
    state.contractDiscovery = {
      status: "error",
      code,
      date,
      ...apiErrorMeta(error, "可用坐标加载失败。"),
    };
  }
  renderCoordinateFields();
}

function renderAvailableStrikes() {
  const expiry = $("availableExpiry").value;
  const strikeSelect = $("availableStrike");
  const status = $("contractCoordinateStatus");
  const applyButton = $("applyContractCoordinate");
  applyButton.disabled = true;
  if (!expiry) {
    strikeSelect.disabled = true;
    strikeSelect.innerHTML = '<option value="">先选择 expiry</option>';
    status.textContent = "请选择一个实际返回 expiry；系统不会自动选取最近日期。";
    return;
  }
  const points = state.contractDiscovery.snapshot.points.filter((point) => point.maturity === expiry);
  const valid = points.filter((point) => point.impliedVol !== null);
  const invalid = points.filter((point) => point.impliedVol === null);
  const uniqueValid = [...new Map(valid.map((point) => [point.strike, point])).values()];
  strikeSelect.innerHTML = `<option value="">请选择有效 strike</option>${uniqueValid
    .map((point) => `<option value="${escapeHtml(point.strike)}">${escapeHtml(point.strike)} · IV ${formatPercent(point.impliedVol)}</option>`)
    .join("")}`;
  strikeSelect.disabled = uniqueValid.length === 0;
  const invalidFlags = [...new Set(invalid.flatMap((point) => point.qualityFlags).filter((flag) => flag !== "OK"))];
  status.textContent = `${expiry}：${uniqueValid.length} 个 strike 有有效 IV；${invalid.length} 个无效坐标保留质量状态但不进入下拉${invalidFlags.length ? `（${invalidFlags.join(", ")}）` : ""}。系统未自动选择 strike。`;
}

function updateContractApplyState() {
  $("applyContractCoordinate").disabled = !$("availableExpiry").value || !$("availableStrike").value;
}

function applyContractCoordinate() {
  const expiry = $("availableExpiry").value;
  const strike = $("availableStrike").value;
  if (!expiry || !strike) return;
  $("maturityRule").value = "fixed";
  $("lowFixedMaturity").value = expiry;
  $("lowFixedStrike").value = strike;
  if ($("highFixedMaturity")) $("highFixedMaturity").value = expiry;
  if ($("highFixedStrike")) $("highFixedStrike").value = strike;
  $("contractCoordinateStatus").textContent = `已明确应用 listed expiry ${expiry} / strike ${strike}（fixed+fixed wire mode）。这是用户选择，不是最近坐标替代。`;
}

function coordinateSelects(labelOne, keyOne, valuesOne, defaultOne, labelTwo, keyTwo, valuesTwo, defaultTwo, compare) {
  return `<div class="coordinate-grid">
    ${selectField(compare ? labelOne : `Low ${labelOne}`, `low${capitalize(keyOne)}`, valuesOne, defaultOne)}
    ${compare ? "" : selectField(`High ${labelOne}`, `high${capitalize(keyOne)}`, valuesOne, defaultOne)}
    ${selectField(compare ? labelTwo : `Low ${labelTwo}`, `low${capitalize(keyTwo)}`, valuesTwo, defaultTwo)}
    ${compare ? "" : selectField(`High ${labelTwo}`, `high${capitalize(keyTwo)}`, valuesTwo, defaultTwo)}
  </div>`;
}

function capitalize(value) { return value.charAt(0).toUpperCase() + value.slice(1); }

function selectField(label, id, values, selected) {
  const options = values.map((value) => `<option value="${escapeHtml(value)}" ${String(value) === String(selected) ? "selected" : ""}>${escapeHtml(value)}</option>`).join("");
  return `<label class="field"><span>${escapeHtml(label)}</span><select id="${id}">${options}</select></label>`;
}

function numberField(label, id, value, step) {
  return `<label class="field"><span>${escapeHtml(label)}</span><input id="${id}" type="number" min="0.000001" step="${step}" value="${value}" /></label>`;
}

function dateField(label, id, value) {
  return `<label class="field"><span>${escapeHtml(label)}</span><input id="${id}" type="date" value="${value}" /></label>`;
}

function renderIndicatorSelector() {
  if (!state.capabilities) return;
  const surfaceOnly = new Set(["smile", "term_structure"]);
  const compareOnly = new Set(["realized_vol", "spot", "forward", "iv_minus_rv", "iv_divided_by_rv", "percentile", "zscore", "correlation"]);
  const indicators = state.capabilities.indicators.filter((id) => (
    state.queryKind === "compare" ? !surfaceOnly.has(id) : !compareOnly.has(id)
  ));
  $("indicatorSelector").innerHTML = indicators.map((id) => `
    <label class="indicator-option"><input type="checkbox" value="${escapeHtml(id)}" ${DEFAULT_INDICATORS.has(id) ? "checked" : ""}/><span>${escapeHtml(INDICATOR_LABELS[id] || id)}</span></label>
  `).join("");
}

function buildVolatilityRequest() {
  const mode = $("requestMode").value;
  const request = {
    code: $("instrumentCode").value.trim(),
    code_type: "bnpp",
    volatility_convention: "bsVol",
    start_date: $("startDate").value,
    end_date: $("endDate").value,
    layout: "matrix",
  };
  const compare = state.queryKind === "compare";
  if (mode === "sliding_moneyness") {
    const strike = Number($("lowStrike").value);
    const maturity = $("lowMaturity").value;
    Object.assign(request, {
      maturity_rule: "sliding",
      strike_rule: $("strikeRule").value,
      low_strike: strike,
      high_strike: compare ? strike : Number($("highStrike").value),
      low_maturity: maturity,
      high_maturity: compare ? maturity : $("highMaturity").value,
    });
  } else if (mode === "sliding_delta") {
    const delta = $("lowDelta").value;
    const maturity = $("lowMaturity").value;
    Object.assign(request, {
      maturity_rule: "sliding",
      strike_rule: "delta",
      low_delta_strike: delta,
      high_delta_strike: compare ? delta : $("highDelta").value,
      low_maturity: maturity,
      high_maturity: compare ? maturity : $("highMaturity").value,
    });
  } else if (mode === "fixed_strike") {
    const strike = Number($("lowFixedStrike").value);
    const expiry = $("lowFixedMaturity").value;
    Object.assign(request, {
      maturity_rule: $("maturityRule").value,
      strike_rule: "fixed",
      low_fixed_strike: strike,
      high_fixed_strike: compare ? strike : Number($("highFixedStrike").value),
      low_fixed_maturity: expiry,
      high_fixed_maturity: compare ? expiry : $("highFixedMaturity").value,
    });
  } else {
    const strike = Number($("lowStrike").value);
    const expiry = $("lowFixedMaturity").value;
    Object.assign(request, {
      maturity_rule: $("maturityRule").value,
      strike_rule: $("strikeRule").value,
      low_strike: strike,
      high_strike: compare ? strike : Number($("highStrike").value),
      low_fixed_maturity: expiry,
      high_fixed_maturity: compare ? expiry : $("highFixedMaturity").value,
    });
  }
  return request;
}

function validateRequest(request) {
  if (!request.code) throw new Error("请输入 instrument code。");
  if (!request.start_date || !request.end_date) throw new Error("请选择完整日期范围。");
  if (request.start_date > request.end_date) throw new Error("开始日期不能晚于结束日期。");
  if (state.queryKind === "compare") {
    const window = Number($("rvWindow").value);
    const minimum = state.capabilities.rvWindowRange.minimum;
    if (!Number.isInteger(window) || window < minimum) {
      throw new Error(`RV window 必须是 ≥ ${minimum} 的整数；不会自动取最近档位。`);
    }
  }
}

async function runQuery(event) {
  event.preventDefault();
  if (state.queryKind === "compare") return;
  $("formError").classList.add("is-hidden");
  let volatilityRequest;
  try {
    volatilityRequest = buildVolatilityRequest();
    validateRequest(volatilityRequest);
  } catch (error) {
    $("formError").textContent = error.message;
    $("formError").classList.remove("is-hidden");
    return;
  }

  const body = { volatilityRequest };
  if (state.queryKind === "compare") {
    body.rvWindowSessions = Number($("rvWindow").value);
    body.rvAlignment = $("rvAlignment").value;
  }
  state.lastRequest = body;
  showLoading();
  const started = performance.now();
  try {
    const endpoint = state.queryKind === "compare"
      ? state.capabilities.endpoints.compare
      : state.capabilities.endpoints.surface;
    const response = await apiFetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    state.lastResponse = await response.json();
    const elapsedMs = Math.round(performance.now() - started);
    state.lastResponse.activity.push({
      code: "BROWSER_RENDER_READY",
      stage: "frontend",
      message: `浏览器已收到完整响应，用时 ${elapsedMs} ms。`,
      affectedObservations: 0,
      suggestedAction: null,
    });
    renderResult();
  } catch (error) {
    showError(error);
  } finally {
    $("runButton").disabled = false;
  }
}

function showLoading() {
  $("runButton").disabled = true;
  $("welcomeState").classList.add("is-hidden");
  $("resultWorkspace").classList.add("is-hidden");
  $("errorPanel").classList.add("is-hidden");
  $("loadingState").classList.remove("is-hidden");
}

function showError(error, fallbackTitle = "查询失败") {
  $("welcomeState").classList.add("is-hidden");
  $("loadingState").classList.add("is-hidden");
  $("resultWorkspace").classList.add("is-hidden");
  $("errorPanel").classList.remove("is-hidden");
  const payload = error.payload || {};
  $("errorTitle").textContent = payload.code || fallbackTitle;
  $("errorMessage").textContent = payload.message || error.message || "未知错误";
  $("errorAction").textContent = payload.suggestedAction ? `建议：${payload.suggestedAction}` : "请检查查询条件后重试。";
  $("errorRequestId").textContent = `Request ID: ${payload.requestId || error.requestId || "—"} · Stage: ${payload.stage || "frontend"}`;
}

function renderResult() {
  $("loadingState").classList.add("is-hidden");
  $("errorPanel").classList.add("is-hidden");
  $("resultWorkspace").classList.remove("is-hidden");
  $("compareCharts").classList.toggle("is-hidden", state.queryKind !== "compare");
  $("surfaceCharts").classList.toggle("is-hidden", state.queryKind !== "surface");
  if (state.queryKind === "compare") renderCompare(); else renderSurface();
  renderQuality();
  renderActivity();
  renderResponseDisclosures();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderCompare() {
  const data = state.lastResponse;
  const method = data.methodology;
  $("resultEyebrow").textContent = "COMPARE RESULT";
  $("resultTitle").textContent = `${data.source.instrumentCode} · ${method.ivLabel}`;
  $("resultSubtitle").textContent = `${method.rvLabel} · ${state.lastRequest.volatilityRequest.start_date} → ${state.lastRequest.volatilityRequest.end_date}`;
  $("cacheBadge").textContent = data.source.cacheStatus.toUpperCase();
  $("requestIdBadge").textContent = `Request ${data.requestId}`;
  renderCompareSummary(data);
  renderCompareCharts(data);
  renderCompareTable(data);
  renderCompareMethodology(data);
  renderWarnings(data);
  renderMissingCoordinateHint(data);
}

function renderCompareSummary(data) {
  const summary = data.summary;
  const indicators = selectedIndicators();
  const cards = [
    ["Latest IV", formatPercent(summary.latestIv), summary.latestIvDate || "无有效 IV", "implied_vol"],
    ["Latest RV", formatPercent(summary.latestRv), data.methodology.rvLabel, "realized_vol"],
    ["Latest spread", summary.latestSpread === null ? "—" : `${formatNumber(summary.latestSpread)} vol pts`, summary.latestComparableDate || "无可比日期", "iv_minus_rv"],
    ["Spread percentile", summary.spreadPercentile === null ? "—" : formatPercent(summary.spreadPercentile, 1), "完整所选历史", "percentile"],
    ["Spread z-score", formatNumber(summary.spreadZScore), "完整所选历史", "zscore"],
    ["IV / RV correlation", formatNumber(summary.correlation, 3), "paired complete", "correlation"],
    ["Observations", formatNumber(summary.observationCount, 0), `${data.dataQuality.usableIvCount} usable IV`, null],
  ].filter((card) => card[3] === null || indicators.has(card[3]));
  $("summaryCards").innerHTML = cards.map(([label, value, note]) => `<article class="summary-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><em>${escapeHtml(note)}</em></article>`).join("");
}

const chartLayout = (yTitle) => ({
  margin: { l: 58, r: 25, t: 22, b: 45 },
  paper_bgcolor: "#fffef9",
  plot_bgcolor: "#fffef9",
  font: { family: "Inter, Microsoft YaHei, sans-serif", size: 10, color: "#536159" },
  hovermode: "x unified",
  xaxis: { gridcolor: "#e8ebe5", zeroline: false },
  yaxis: { title: yTitle, gridcolor: "#e8ebe5", zeroline: false },
  legend: { orientation: "h", x: 0, y: 1.12 },
});

const plotConfig = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d"] };

function renderCompareCharts(data) {
  const indicators = selectedIndicators();
  const dates = data.series.map((point) => point.date);
  const qualityText = data.series.map((point) => point.qualityFlags.join(", "));
  const traces = [];
  if (indicators.has("implied_vol")) traces.push(lineTrace(dates, data.series.map((point) => point.impliedVol), data.methodology.ivLabel, "#0f7554", qualityText));
  if (indicators.has("realized_vol")) traces.push(lineTrace(dates, data.series.map((point) => point.realizedVol), data.methodology.rvLabel, "#3557a4", qualityText));
  if (indicators.has("iv_minus_rv")) traces.push(lineTrace(dates, data.series.map((point) => point.ivMinusRv), "IV − RV · vol points", "#d66a2d", qualityText, "dot"));
  Plotly.react("volChart", traces, chartLayout("Volatility / vol points (%)"), plotConfig);
  $("volChartTitle").textContent = `${data.methodology.ivLabel} / ${data.methodology.rvLabel}`;

  const priceTraces = [];
  if (indicators.has("spot")) priceTraces.push(lineTrace(dates, data.series.map((point) => point.spot), "Spot · 原始未复权", "#17211c", qualityText));
  if (indicators.has("forward")) priceTraces.push(lineTrace(dates, data.series.map((point) => point.forward), "Forward", "#8c6bb1", qualityText, "dash"));
  Plotly.react("priceChart", priceTraces, chartLayout("Price"), plotConfig);
}

function lineTrace(x, y, name, color, text, dash = "solid") {
  return {
    x, y, name, text,
    type: "scatter",
    mode: "lines+markers",
    connectgaps: false,
    line: { color, width: 2, dash },
    marker: { color, size: 5 },
    hovertemplate: "%{x}<br>%{y:.3f}<br>%{text}<extra>%{fullData.name}</extra>",
  };
}

function renderCompareTable(data) {
  const headers = ["Date", "Spot · unadjusted", "Forward", "Raw IV %", "Effective IV %", "RV %", "IV−RV vol pts", "IV/RV", "Quality flags"];
  $("resultTableHead").innerHTML = `<tr>${headers.map((item) => `<th>${escapeHtml(item)}</th>`).join("")}</tr>`;
  $("resultTableBody").innerHTML = data.series.map((point) => `<tr>
    <td>${point.date}</td><td>${tableValue(point.spot)}</td><td>${tableValue(point.forward)}</td>
    <td>${tableValue(point.rawImpliedVol)}</td><td>${tableValue(point.impliedVol)}</td><td>${tableValue(point.realizedVol)}</td>
    <td>${tableValue(point.ivMinusRv)}</td><td>${tableValue(point.ivDividedByRv, 4)}</td><td>${flagHtml(point.qualityFlags)}</td>
  </tr>`).join("");
  $("tableTitle").textContent = "IV / RV 时间序列明细";
  $("tableCount").textContent = `${data.series.length} rows`;
  $("tableFootnote").textContent = "Raw IV 保留上游值；effective IV 为空的点不会在图中连接，也不进入统计。";
}

function renderCompareMethodology(data) {
  const method = data.methodology;
  $("methodologyContent").innerHTML = definitionGrid([
    ["IV", method.ivLabel], ["RV", method.rvLabel], ["RV formula", method.rvFormula],
    ["Annualization", `${method.annualization} trading sessions`], ["Vol units", "percent；spread = vol points"],
    ["Spot", method.spotNote], ["Corporate action adjustment", method.corporateActionAdjustment],
    ["Provider", `${data.source.provider} · API ${data.source.apiVersion}`], ["Retrieved at", data.source.retrievedAt],
  ]);
}

function renderWarnings(data) {
  const messages = [];
  if (data.dataQuality.warningBanner) messages.push(data.dataQuality.warningBanner);
  data.activity.filter((event) => ["FORWARD_RV_INCOMPLETE", "LARGE_SURFACE_RESULT"].includes(event.code)).forEach((event) => messages.push(event.message));
  $("warningBanner").classList.toggle("is-hidden", messages.length === 0);
  $("warningBanner").innerHTML = messages.map((message) => `<strong>WARNING</strong> · ${escapeHtml(message)}`).join("<br>");
}

function renderMissingCoordinateHint(data) {
  const missing = data.series.filter((point) => point.qualityFlags.some((flag) => ["MISSING_IV", "MATURITY_MISMATCH", "STRIKE_MISMATCH"].includes(flag)));
  const hint = $("coordinateHint");
  if (!missing.length) {
    hint.classList.add("is-hidden");
    return;
  }
  hint.classList.remove("is-hidden");
  hint.innerHTML = `<strong>精确坐标缺失：</strong>${missing.length} 个日期没有请求坐标的数据。系统未使用邻近值。可切换到 Surface 并扩大 strike/expiry 范围；页面会显示实际返回坐标，供你判断最近可用的 strike 或 expiry。`;
}

function renderSurface() {
  const data = state.lastResponse;
  const request = state.lastRequest.volatilityRequest;
  $("resultEyebrow").textContent = "SURFACE RESULT";
  $("resultTitle").textContent = `${data.source.instrumentCode} · ${surfaceLabel(request)}`;
  $("resultSubtitle").textContent = `${request.start_date} → ${request.end_date} · 完整坐标范围`;
  $("cacheBadge").textContent = data.source.cacheStatus.toUpperCase();
  $("requestIdBadge").textContent = `Request ${data.requestId}`;
  $("snapshotDate").innerHTML = data.snapshots.map((snapshot) => `<option value="${snapshot.date}">${snapshot.date} · ${snapshot.points.length} points</option>`).join("");
  renderSurfaceSummary(data);
  renderSurfaceMethodology(data, request);
  renderWarnings(data);
  renderSurfaceSnapshot();
}

function surfaceLabel(request) {
  const strike = request.strike_rule === "relative_to_forward" ? "K/F" : request.strike_rule === "relative_to_spot_ref" ? "K/S" : request.strike_rule === "delta" ? "Delta" : "Absolute strike";
  return `${request.maturity_rule} · ${strike}`;
}

function renderSurfaceSummary(data) {
  const quality = data.dataQuality;
  const cards = [
    ["Snapshots", formatNumber(quality.snapshotCount, 0), "business dates"],
    ["Surface points", formatNumber(quality.pointCount, 0), "完整响应未截断"],
    ["Usable IV", formatNumber(quality.usableIvCount, 0), "effective points"],
    ["Invalid IV", formatNumber(quality.invalidIvCount, 0), "raw retained · effective null"],
  ];
  $("summaryCards").innerHTML = cards.map(([label, value, note]) => `<article class="summary-card"><small>${label}</small><strong>${value}</strong><em>${note}</em></article>`).join("");
}

function renderSurfaceSnapshot() {
  if (state.queryKind !== "surface" || !state.lastResponse) return;
  const date = $("snapshotDate").value || state.lastResponse.snapshots[0]?.date;
  const snapshot = state.lastResponse.snapshots.find((item) => item.date === date);
  if (!snapshot) return;
  const indicators = selectedIndicators();
  const smileTraces = snapshot.maturities.map((maturity) => {
    const points = snapshot.points.filter((point) => point.maturity === maturity).sort((a, b) => a.strikeIndex - b.strikeIndex);
    return lineTrace(points.map((point) => point.strike), points.map((point) => point.impliedVol), maturity, colorFor(maturity), points.map((point) => point.qualityFlags.join(", ")));
  });
  const termTraces = snapshot.strikes.map((strike) => {
    const points = snapshot.points.filter((point) => point.strike === strike).sort((a, b) => a.maturityIndex - b.maturityIndex);
    return lineTrace(points.map((point) => point.maturity), points.map((point) => point.impliedVol), strike, colorFor(strike), points.map((point) => point.qualityFlags.join(", ")));
  });
  Plotly.react("smileChart", indicators.has("smile") ? smileTraces : [], chartLayout("Implied volatility (%)"), plotConfig);
  Plotly.react("termChart", indicators.has("term_structure") ? termTraces : [], chartLayout("Implied volatility (%)"), plotConfig);
  $("surfaceCoordinateSummary").textContent = `${snapshot.maturities.length} maturities × ${snapshot.strikes.length} strikes · Spot ${formatNumber(snapshot.spot)}`;
  renderSurfaceCoordinateHint(snapshot);
  renderSurfaceTable(snapshot);
}

function colorFor(value) {
  const palette = ["#0f7554", "#3557a4", "#d66a2d", "#8c6bb1", "#bf3d5d", "#4e8f9c", "#8e7b28"];
  let hash = 0;
  for (const character of String(value)) hash = ((hash << 5) - hash) + character.charCodeAt(0);
  return palette[Math.abs(hash) % palette.length];
}

function renderSurfaceCoordinateHint(snapshot) {
  const hint = $("coordinateHint");
  if (!snapshot.points.length) {
    hint.classList.remove("is-hidden");
    hint.innerHTML = "<strong>当前日期没有可用 surface 坐标。</strong> 这是缺失数据，系统没有选邻近坐标。可扩大 expiry 或 strike 查询范围以查看实际可用坐标。";
    return;
  }
  const request = state.lastRequest.volatilityRequest;
  const targetStrike = Number(request.low_fixed_strike ?? request.low_strike);
  const targetExpiry = request.low_fixed_maturity;
  const strikeValues = snapshot.strikes.map(Number).filter(Number.isFinite);
  const nearestStrike = Number.isFinite(targetStrike) && strikeValues.length
    ? strikeValues.reduce((best, value) => Math.abs(value - targetStrike) < Math.abs(best - targetStrike) ? value : best)
    : null;
  const nearestExpiry = targetExpiry && snapshot.maturities.length
    ? snapshot.maturities.reduce((best, value) => Math.abs(Date.parse(value) - Date.parse(targetExpiry)) < Math.abs(Date.parse(best) - Date.parse(targetExpiry)) ? value : best)
    : null;
  if (nearestStrike === null && nearestExpiry === null) {
    hint.classList.add("is-hidden");
    return;
  }
  const parts = [];
  if (nearestStrike !== null) parts.push(`最近返回 strike：${nearestStrike}`);
  if (nearestExpiry !== null) parts.push(`最近返回 expiry：${nearestExpiry}`);
  hint.classList.remove("is-hidden");
  hint.innerHTML = `<strong>坐标参考（不会替代请求）：</strong>${escapeHtml(parts.join("；"))}。`;
}

function renderSurfaceTable(snapshot) {
  const rows = snapshot.points;
  const renderLimit = 1000;
  const visible = rows.slice(0, renderLimit);
  const headers = ["Date", "Maturity / expiry", "Strike / delta", "Raw IV %", "Effective IV %", "Quality flags"];
  $("resultTableHead").innerHTML = `<tr>${headers.map((item) => `<th>${escapeHtml(item)}</th>`).join("")}</tr>`;
  $("resultTableBody").innerHTML = visible.map((point) => `<tr><td>${snapshot.date}</td><td>${escapeHtml(point.maturity)}</td><td>${escapeHtml(point.strike)}</td><td>${tableValue(point.rawImpliedVol)}</td><td>${tableValue(point.impliedVol)}</td><td>${flagHtml(point.qualityFlags)}</td></tr>`).join("");
  $("tableTitle").textContent = `Surface 明细 · ${snapshot.date}`;
  $("tableCount").textContent = `${rows.length} points`;
  $("tableFootnote").textContent = rows.length > renderLimit
    ? `为避免页面卡顿，表格只显示当前日期前 ${renderLimit} 个点；完整响应未截断，CSV 会导出全部日期和全部点。`
    : "当前表格显示所选日期的全部返回点；CSV 会导出全部日期。";
}

function renderSurfaceMethodology(data, request) {
  $("methodologyContent").innerHTML = definitionGrid([
    ["Mode", surfaceLabel(request)], ["Vol convention", request.volatility_convention], ["Layout", request.layout],
    ["Chart scope", "只渲染当前日期切片；响应与 CSV 保留全部点"],
    ["Invalid IV", "raw value 保留；effective value = null；不连接"],
    ["Coordinate fallback", "none；最近坐标只作提示"],
    ["Provider", `${data.source.provider} · API ${data.source.apiVersion}`], ["Retrieved at", data.source.retrievedAt],
  ]);
}

function renderQuality() {
  const quality = state.lastResponse.dataQuality;
  $("qualityStatus").textContent = quality.status;
  const counts = state.queryKind === "compare"
    ? [["Observations", quality.observationCount], ["Usable IV", quality.usableIvCount], ["Invalid IV", quality.invalidIvCount]]
    : [["Snapshots", quality.snapshotCount], ["Usable IV", quality.usableIvCount], ["Invalid IV", quality.invalidIvCount]];
  const flagEntries = Object.entries(quality.flagCounts || {});
  $("qualityContent").innerHTML = `<div class="quality-counts">${counts.map(([label, value]) => `<div class="quality-count"><small>${label}</small><strong>${formatNumber(value, 0)}</strong></div>`).join("")}</div>
    <div class="quality-flags">${flagEntries.length ? flagEntries.map(([flag, count]) => `<span class="flag-chip">${escapeHtml(flag)} · ${count}</span>`).join("") : '<span class="flag-chip">OK · no flags</span>'}</div>
    <p class="inline-note">${escapeHtml(quality.analyticsExclusionPolicy)}</p>`;
}

function renderActivity() {
  $("activityList").innerHTML = state.lastResponse.activity.map((event) => `<li>
    <span class="activity-stage">${escapeHtml(event.stage)}</span>
    <div class="activity-message"><strong>${escapeHtml(event.code)}${event.affectedObservations ? ` · ${formatNumber(event.affectedObservations, 0)}` : ""}</strong><p>${escapeHtml(event.message)}</p>${event.suggestedAction ? `<p class="activity-action">建议：${escapeHtml(event.suggestedAction)}</p>` : ""}</div>
  </li>`).join("");
}

function renderBuilderDisclosures() {
  // Generic rules are not request warnings. They are shown on demand in the
  // result-side Methodology & Rules section instead of occupying the query rail.
}

function renderResponseDisclosures() {
  const context = new Set([
    state.queryKind,
    "implied_vol",
    "source_metadata",
    "upstream_fetch",
    "cache",
    ...(state.queryKind === "compare" ? ["realized_vol", "spot", "forward", "csv"] : []),
    ...selectedIndicators(),
  ]);
  const disclosures = state.lastResponse.disclosures || [];
  for (const [surface, id] of Object.entries(FRONTEND_SURFACE_IDS)) {
    if (surface === "query_builder") continue;
    renderDisclosureEntries($(id), applicableDisclosures(disclosures, context, surface));
  }
}

function applicableDisclosures(disclosures, context, frontendSurface) {
  return disclosures.filter((entry) => entry.frontendRequired
    && entry.frontendSurfaces.includes(frontendSurface)
    && entry.appliesTo.some((target) => context.has(target)));
}

function renderDisclosureEntries(container, entries) {
  container.innerHTML = entries.map((entry) => `<article class="disclosure-item ${entry.severity === "warning" ? "warning" : ""}" data-disclosure-id="${escapeHtml(entry.id)}">
    <h4>${entry.severity.toUpperCase()} · ${escapeHtml(entry.title)}</h4><p>${escapeHtml(entry.summary)}</p>
    <details><summary>查看细节</summary><ul>${entry.details.map((detail) => `<li>${escapeHtml(detail)}</li>`).join("")}</ul></details>
  </article>`).join("");
}

// Results are rendered as an explicit clickable list rather than a <datalist>: browsers
// filter datalist options against the typed text, so searching "9998" would hide a match
// whose code is "HK_9998", and options injected after the field has focus are not always
// re-read. An explicit list always shows exactly what the catalogue returned.
async function searchInstruments() {
  const query = $("instrumentCode").value.trim();
  $("instrumentHelp").textContent = "正在搜索 instrument catalogue…";
  try {
    const endpoint = `${state.capabilities.endpoints.instruments}?q=${encodeURIComponent(query)}&type=equity&maxResults=50`;
    const response = await apiFetch(endpoint);
    const data = await response.json();
    renderInstrumentResults(data.instruments || []);
    $("instrumentHelp").textContent = data.hasMore
      ? `匹配 ${data.matchedCount} 项，仅显示前 ${data.returnedCount} 项；请缩小关键词后重新搜索。`
      : `匹配 ${data.matchedCount} 项；点击下方结果即可选用。`;
  } catch (error) {
    hideInstrumentResults();
    $("instrumentHelp").textContent = `搜索失败：${apiErrorSummary(error, "instrument catalogue 搜索失败")}`;
  }
}

function renderInstrumentResults(instruments) {
  const box = $("instrumentResults");
  if (!instruments.length) {
    box.innerHTML = '<p class="instrument-empty">没有匹配的 instrument。</p>';
    box.classList.remove("is-hidden");
    return;
  }
  box.innerHTML = instruments.map((item) => {
    const meta = [item.type, item.marketName, item.currencyCode].filter(Boolean).join(" · ");
    return `<button type="button" class="instrument-result" role="option" data-instrument-code="${escapeHtml(item.code)}">
      <strong>${escapeHtml(item.code)}</strong>
      <span>${escapeHtml(item.companyName || item.bbgCode || "")}</span>
      ${meta ? `<em>${escapeHtml(meta)}</em>` : ""}
    </button>`;
  }).join("");
  box.classList.remove("is-hidden");
}

function hideInstrumentResults() {
  $("instrumentResults").classList.add("is-hidden");
  $("instrumentResults").innerHTML = "";
}

function selectInstrument(code) {
  const input = $("instrumentCode");
  input.value = code;
  // Everything downstream listens on the input, so replay the events a manual edit fires.
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  hideInstrumentResults();
  $("instrumentHelp").textContent = `已选择 ${code}。`;
}

async function downloadCsv() {
  if (state.queryKind === "compare" && window.volcurveCompareDetails?.downloadSelectedCsv) {
    await window.volcurveCompareDetails.downloadSelectedCsv();
    return;
  }
  if (!state.lastResponse || !state.lastRequest) return;
  if (state.queryKind === "compare") {
    try {
      const response = await apiFetch(state.capabilities.endpoints.compareCsv, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state.lastRequest),
      });
      saveBlob(await response.blob(), `${state.lastRequest.volatilityRequest.code}_vol_compare.csv`);
    } catch (error) {
      showError(error, "CSV 生成失败");
    }
    return;
  }
  const header = ["date", "spot", "maturity", "strike", "raw_implied_vol", "implied_vol", "quality_flags"];
  const rows = [header];
  for (const snapshot of state.lastResponse.snapshots) {
    for (const point of snapshot.points) {
      rows.push([snapshot.date, snapshot.spot, point.maturity, point.strike, point.rawImpliedVol, point.impliedVol, point.qualityFlags.join("|")]);
    }
  }
  const csv = rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
  saveBlob(new Blob([csv], { type: "text/csv;charset=utf-8" }), `${state.lastRequest.volatilityRequest.code}_vol_surface.csv`);
}

function csvCell(value) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function tableValue(value, digits = 3) {
  return value === null || value === undefined
    ? '<span class="cell-missing">—</span>'
    : escapeHtml(formatNumber(value, digits));
}

function flagHtml(flags) {
  const nonOk = flags.filter((flag) => flag !== "OK");
  return nonOk.length ? nonOk.map((flag) => `<span class="flag-chip">${escapeHtml(flag)}</span>`).join("") : "OK";
}

function definitionGrid(entries) {
  return `<dl class="definition-grid">${entries.map(([term, definition]) => `<dt>${escapeHtml(term)}</dt><dd>${escapeHtml(definition)}</dd>`).join("")}</dl>`;
}

window.addEventListener("DOMContentLoaded", initialize);
