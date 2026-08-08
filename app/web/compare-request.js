"use strict";

// Cortex request construction, exact-coordinate discovery, fetch lifecycle and series
// resolution for the Time Series workspace. No chart/table rendering lives here.

async function loadListedStrikes(expiry) {
  const code = indicatorState.draft.instrumentCode.trim();
  const date = indicatorState.listedObservationDate || $("indicatorObservationDate")?.value || indicatorState.discovery?.date || $("endDate")?.value;
  if (!code || !date || !expiry) return;
  const discovery = indicatorState.discovery;
  if (!discovery || discovery.code !== code || discovery.date !== date || discovery.status !== "ready") return;
  if (discovery.strikeStatus === "loading" && discovery.strikeExpiry === expiry) return;
  const requestSeq = (indicatorState.strikeRequestSeq || 0) + 1;
  indicatorState.strikeRequestSeq = requestSeq;
  indicatorState.discovery = { ...discovery, strikeStatus: "loading", strikeExpiry: expiry, strikeMessage: null, strikes: [] };
  renderIndicatorConfig();
  try {
    const response = await apiFetch(state.capabilities.endpoints.surface, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ volatilityRequest: {
        code, code_type: "bnpp", volatility_convention: "bsVol", start_date: date, end_date: date,
        maturity_rule: "listed", strike_rule: "fixed", low_fixed_maturity: expiry,
        high_fixed_maturity: expiry, layout: "matrix",
      }}),
    });
    const payload = await response.json();
    if (indicatorState.strikeRequestSeq !== requestSeq || indicatorState.draft.maturityMode !== "listed"
      || indicatorState.draft.strikeKind !== "absolute" || indicatorState.draft.instrumentCode.trim() !== code
      || indicatorState.listedObservationDate !== date || indicatorState.draft.expiry !== expiry) return;
    const snapshot = payload.snapshots?.find((item) => item.date === date);
    if (!snapshot) throw new Error("No listed strike surface returned for this observation date.");
    const strikes = [...new Set((snapshot.points || [])
      .filter((point) => point.maturity === expiry).map((point) => Number(point.strike))
      .filter((value) => Number.isFinite(value) && value > 0))].sort((a, b) => a - b);
    indicatorState.discovery = { ...indicatorState.discovery, strikeStatus: "ready", strikeExpiry: expiry,
      strikeMessage: null, strikeSnapshot: snapshot, strikes: strikes.map(String) };
  } catch (error) {
    if (indicatorState.strikeRequestSeq !== requestSeq || indicatorState.draft.maturityMode !== "listed"
      || indicatorState.draft.strikeKind !== "absolute" || indicatorState.draft.instrumentCode.trim() !== code
      || indicatorState.listedObservationDate !== date || indicatorState.draft.expiry !== expiry) return;
    const meta = apiErrorMeta(error, "available strikes 加载失败");
    indicatorState.discovery = { ...indicatorState.discovery, strikeStatus: "error", strikeExpiry: expiry,
      strikeMessage: meta.message, strikeErrorCode: meta.errorCode, strikeSuggestedAction: meta.suggestedAction,
      strikeSuggestedActionSource: meta.suggestedActionSource, strikeRequestId: meta.requestId, strikeStage: meta.stage, strikes: [] };
  }
  renderIndicatorConfig();
}

async function loadIndicatorCoordinates(dateOverride = "") {
  const code = indicatorState.draft.instrumentCode.trim();
  const date = dateOverride || indicatorState.listedObservationDate || $("indicatorObservationDate")?.value || $("endDate")?.value;
  if (!code || !date) {
    indicatorState.discovery = { status: "error", code, date, message: "Instrument code and observation date are required." };
    renderIndicatorConfig(); return;
  }
  indicatorState.listedObservationDate = date;
  const current = indicatorState.discovery;
  if (current?.status === "loading" && current.code === code && current.date === date) return;
  const requestSeq = (indicatorState.discoveryRequestSeq || 0) + 1;
  indicatorState.discoveryRequestSeq = requestSeq;
  indicatorState.discovery = { status: "loading", code, date };
  renderIndicatorConfig();
  try {
    const response = await apiFetch(state.capabilities.endpoints.surface, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ volatilityRequest: {
        code, code_type: "bnpp", volatility_convention: "bsVol", start_date: date, end_date: date,
        maturity_rule: "listed", strike_rule: "relative_to_forward", low_strike: 100, high_strike: 100, layout: "matrix",
      }}),
    });
    const payload = await response.json();
    if (indicatorState.discoveryRequestSeq !== requestSeq || indicatorState.draft.maturityMode !== "listed"
      || indicatorState.draft.instrumentCode.trim() !== code || indicatorState.listedObservationDate !== date) return;
    const snapshot = payload.snapshots?.find((item) => item.date === date);
    if (!snapshot) throw new Error("No listed surface returned for this observation date.");
    const maturities = [...new Set(snapshot.maturities || [])].sort();
    if (indicatorState.draft.expiry && !maturities.includes(indicatorState.draft.expiry)) indicatorState.draft.expiry = "";
    indicatorState.discovery = { status: "ready", code, date, snapshot: { ...snapshot, maturities } };
  } catch (error) {
    if (indicatorState.discoveryRequestSeq !== requestSeq || indicatorState.draft.maturityMode !== "listed"
      || indicatorState.draft.instrumentCode.trim() !== code || indicatorState.listedObservationDate !== date) return;
    indicatorState.discovery = { status: "error", code, date, ...apiErrorMeta(error, "listed expiries 加载失败") };
  }
  renderIndicatorConfig();
}

function validateScope(config) {
  if (!state.capabilities) throw new Error("Capability registry 尚未载入，请稍后重试。");
  if (config?.type !== "derived" && !config?.instrumentCode?.trim()) throw new Error("请输入该 indicator 的 instrument code。");
  if (!$("startDate").value || !$("endDate").value) throw new Error("请选择完整日期范围。");
  if ($("startDate").value > $("endDate").value) throw new Error("开始日期不能晚于结束日期。");
}

function validateDraft(draft) {
  if (draft.type === "derived") {
    const left = itemById(draft.operandA); const right = itemById(draft.operandB);
    if (!left || !right) throw new Error("请选择两个已保存的 indicator 作为操作数。");
    if (!Object.hasOwn(OPERATOR_SYMBOLS, draft.operator)) throw new Error("请选择合法的运算符。");
    if (indicatorState.editingId !== null) {
      const blocked = dependencyClosure(indicatorState.editingId);
      if (blocked.has(left.id) || blocked.has(right.id)) throw new Error("运算指标不能引用自己，也不能引用依赖它的指标。");
    }
    return;
  }
  if (["implied_vol", "forward"].includes(draft.type)) {
    if (draft.maturityMode === "sliding") {
      const supported = draft.strikeKind === "delta" ? state.capabilities.deltaMaturities : state.capabilities.slidingMaturities;
      if (!supported.includes(draft.slidingMaturity)) throw new Error(`数据源 OpenAPI 不接受 sliding maturity ${draft.slidingMaturity || "(空)"}；请输入官方 tenor。`);
    } else if (!validIsoDate(draft.expiry)) throw new Error("请输入合法的 fixed/listed expiry 日期。");
  }
  if (draft.type === "implied_vol") {
    if (draft.strikeKind === "percentage") {
      const value = Number(draft.moneyness);
      if (!state.capabilities.moneynessLevels.some((level) => Number(level) === value)) throw new Error(`数据源 OpenAPI 不接受 moneyness ${draft.moneyness || "(空)"}；请输入官方离散档位。`);
    } else if (draft.strikeKind === "delta") {
      if (draft.maturityMode !== "sliding" || !state.capabilities.deltaStrikes.includes(draft.delta)) throw new Error("Delta 只接受 sliding maturity 与数据源官方 delta code。");
    } else if (!(Number(draft.absoluteStrike) > 0)) throw new Error("Absolute strike 必须是正数。");
  }
  if (draft.type === "realized_vol") {
    const window = Number(draft.rvWindow); const minimum = state.capabilities.rvWindowRange.minimum;
    if (!Number.isInteger(window) || window < minimum) throw new Error(`RV window 必须是 ≥ ${minimum} 的整数；不会自动取最近档位。`);
  }
}

function buildIndicatorRequest(item) {
  const base = {
    code: item.config.instrumentCode.trim(), code_type: "bnpp", volatility_convention: "bsVol",
    start_date: $("startDate").value, end_date: $("endDate").value, layout: "matrix",
  };
  let volatilityRequest;
  if (item.type === "implied_vol") volatilityRequest = coordinateRequest(base, item.config, true);
  else if (item.type === "forward") volatilityRequest = coordinateRequest(base, { ...item.config, strikeKind: "percentage", moneynessBasis: "relative_to_forward", moneyness: "100" }, false);
  else volatilityRequest = coordinateRequest(base, defaultDraft("implied_vol"), false);
  const wantsRealizedVol = item.type === "realized_vol";
  return { volatilityRequest, rvWindowSessions: wantsRealizedVol ? Number(item.config.rvWindow) : 2,
    rvAlignment: wantsRealizedVol ? item.config.rvAlignment : "trailing", includeRealizedVol: wantsRealizedVol };
}

function coordinateRequest(base, config, includeStrikeChoice) {
  if (config.maturityMode === "sliding") {
    if (includeStrikeChoice && config.strikeKind === "delta") {
      return { ...base, maturity_rule: "sliding", strike_rule: "delta", low_delta_strike: config.delta,
        high_delta_strike: config.delta, low_maturity: config.slidingMaturity, high_maturity: config.slidingMaturity };
    }
    const strike = includeStrikeChoice ? Number(config.moneyness) : 100;
    return { ...base, maturity_rule: "sliding", strike_rule: includeStrikeChoice ? config.moneynessBasis : "relative_to_forward",
      low_strike: strike, high_strike: strike, low_maturity: config.slidingMaturity, high_maturity: config.slidingMaturity };
  }
  if (includeStrikeChoice && config.strikeKind === "absolute") {
    const strike = Number(config.absoluteStrike);
    return { ...base, maturity_rule: config.maturityMode, strike_rule: "fixed", low_fixed_strike: strike,
      high_fixed_strike: strike, low_fixed_maturity: config.expiry, high_fixed_maturity: config.expiry };
  }
  const strike = includeStrikeChoice ? Number(config.moneyness) : 100;
  return { ...base, maturity_rule: config.maturityMode, strike_rule: includeStrikeChoice ? config.moneynessBasis : "relative_to_forward",
    low_strike: strike, high_strike: strike, low_fixed_maturity: config.expiry, high_fixed_maturity: config.expiry };
}

async function fetchIndicator(item, { force = false } = {}) {
  if (!indicatorState.items.some((candidate) => candidate.id === item.id)) return;
  if (item.type === "derived") { refreshWorkspacePanels(); return; }
  item.status = "loading"; item.error = null; refreshWorkspacePanels(); const started = performance.now();
  try {
    validateScope(item.config); item.request = buildIndicatorRequest(item);
    const response = await apiFetch(state.capabilities.endpoints.compare, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(force ? { ...item.request, forceRefresh: true } : item.request),
    });
    const payload = await response.json();
    if (!indicatorState.items.some((candidate) => candidate.id === item.id)) return;
    payload.activity.push({ code: "BROWSER_RENDER_READY", stage: "frontend",
      message: `浏览器已收到该 indicator 的完整响应，用时 ${Math.round(performance.now() - started)} ms。`,
      affectedObservations: 0, suggestedAction: null });
    item.response = payload; item.status = "ready";
  } catch (error) { item.status = "error"; item.error = apiErrorSummary(error, "指标加载失败"); item.response = null; }
  refreshWorkspacePanels();
}

async function refreshActiveIndicators({ force = false } = {}) {
  hideIndicatorFormError();
  if (syncSlidingRange()) { renderDateMode(); persistWorkspace(); }
  const fetchable = itemsNeedingData().filter((item) => item.type !== "derived");
  await Promise.all(fetchable.map((item) => fetchIndicator(item, { force })));
  refreshWorkspacePanels();
}
async function forceRefreshActiveIndicators() { await refreshActiveIndicators({ force: true }); }
function itemsNeedingData() {
  const needed = new Set(indicatorState.items.filter((item) => item.active).map((item) => item.id)); let grew = true;
  while (grew) { grew = false; for (const item of indicatorState.items) {
    if (item.type !== "derived" || !needed.has(item.id)) continue;
    for (const reference of [item.config.operandA, item.config.operandB]) { const operand = itemById(reference); if (operand && !needed.has(operand.id)) { needed.add(operand.id); grew = true; } }
  }}
  return indicatorState.items.filter((item) => needed.has(item.id));
}
function isNeededButHidden(item) { return !item.active && itemsNeedingData().some((needed) => needed.id === item.id); }
function fetchMissingDependencies() { for (const item of itemsNeedingData()) if (item.type !== "derived" && !item.response && item.status !== "loading") fetchIndicator(item); }
function invalidateIndicators() {
  indicatorState.discovery = null;
  for (const item of indicatorState.items) if (item.type !== "derived") { item.status = "stale"; item.response = null; item.error = null; }
  persistWorkspace(); refreshWorkspacePanels();
}

function refreshWorkspacePanels({ details = true } = {}) {
  refreshSeriesIndex(); renderSavedIndicators(); renderIndicatorChart(); renderIndicatorStats();
  renderCrosshairReadout(indicatorState.hoverDate); if (details) renderIndicatorDetails();
}
function refreshSeriesIndex() {
  const index = new Map(); for (const item of indicatorState.items) resolveSeries(item, index, new Set()); indicatorState.seriesIndex = index;
}
function resolveSeries(item, index, stack) {
  if (index.has(item.id)) return index.get(item.id);
  let entry;
  if (item.type === "derived") { entry = computeDerivedSeries(item, index, stack); item.status = entry.error ? "error" : "ready"; item.error = entry.error; }
  else if (item.status === "ready" && item.response) {
    const key = indicatorValueKey(item.type);
    entry = { points: item.response.series.map((point) => ({ date: point.date, value: numericValue(point[key]) })), error: null };
  } else entry = { points: null, error: item.error || indicatorStatus(item) };
  entry.byDate = entry.points ? new Map(entry.points.map((point) => [point.date, point.value])) : new Map(); index.set(item.id, entry); return entry;
}
function computeDerivedSeries(item, index, stack) {
  if (stack.has(item.id)) return { points: null, error: "指标运算的引用形成了循环。" };
  const config = item.config; const left = itemById(config.operandA); const right = itemById(config.operandB);
  if (!left || !right) return { points: null, error: "引用的 indicator 已不存在，无法计算。" };
  if (!Object.hasOwn(OPERATOR_SYMBOLS, config.operator)) return { points: null, error: "运算符不合法。" };
  const nested = new Set(stack).add(item.id); const leftEntry = resolveSeries(left, index, nested); const rightEntry = resolveSeries(right, index, nested);
  if (!leftEntry.points) return { points: null, error: `操作数「${indicatorLabel(left)}」不可用：${leftEntry.error}` };
  if (!rightEntry.points) return { points: null, error: `操作数「${indicatorLabel(right)}」不可用：${rightEntry.error}` };
  const points = deriveSeries(leftEntry.points, rightEntry.points, config.operator);
  return points.length ? { points, error: null } : { points: null, error: "两个操作数在当前日期范围内没有共同观察日。" };
}
