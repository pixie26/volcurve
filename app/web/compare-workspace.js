"use strict";

// Mutable Time Series workspace and persistence.  Rendering/fetching live in separate files;
// this module owns the saved state and the mutations that change it.
const STORAGE_KEY = "volcurve.compare.workspace.v1";
const BOARD_STORAGE_KEY = "volcurve.compare.boards.v1";
const STATS_STORAGE_KEY = "volcurve.compare.statscolumns.v1";
const MAX_CHARTS = 8;
const SLIDING_WINDOWS = [
  { id: "1M", label: "1M" }, { id: "3M", label: "3M" }, { id: "6M", label: "6M" },
  { id: "YTD", label: "YTD" }, { id: "1Y", label: "1Y" }, { id: "2Y", label: "2Y" },
  { id: "3Y", label: "3Y" }, { id: "5Y", label: "5Y" }, { id: "10Y", label: "10Y" },
];
const STATS_LABEL_COLUMN = "__label__";
const DEFAULT_LABEL_WIDTH = 190;
const DEFAULT_SERIES_WIDTH = 150;
const MIN_COLUMN_WIDTH = 80;
const MIN_AUTO_SERIES_WIDTH = 72;
const TYPE_LABELS = {
  implied_vol: "Implied volatility", realized_vol: "Realized volatility", spot: "Spot",
  forward: "Forward", derived: "Derived",
};
const OPERATOR_SYMBOLS = { add: "＋", subtract: "−", multiply: "×", divide: "÷" };
const VOL_TYPES = new Set(["implied_vol", "realized_vol"]);
const PRICE_TYPES = new Set(["spot", "forward"]);
const PALETTE = ["#0f7554", "#3557a4", "#d66a2d", "#8c6bb1", "#bf3d5d", "#4e8f9c", "#8e7b28"];
const STAT_COLUMNS = [
  { id: "lane", label: "坐标", kind: "text" },
  { id: "count", label: "观测数", kind: "count" },
  { id: "latest", label: "最新值", kind: "value" },
  { id: "latestDate", label: "最新日期", kind: "text" },
  { id: "change1", label: "1D 变化", kind: "signed" },
  { id: "change5", label: "5D 变化", kind: "signed" },
  { id: "change20", label: "20D 变化", kind: "signed" },
  { id: "change60", label: "60D 变化", kind: "signed", defaultVisible: false },
  { id: "min", label: "最小", kind: "value" },
  { id: "max", label: "最大", kind: "value" },
  { id: "range", label: "区间 (最大−最小)", kind: "value" },
  { id: "mean", label: "平均", kind: "value" },
  { id: "mean20", label: "20D 均值", kind: "value" },
  { id: "mean60", label: "60D 均值", kind: "value", defaultVisible: false },
  { id: "vsMean20", label: "最新值 − 20D 均值", kind: "signed", defaultVisible: false },
  { id: "median", label: "中位数", kind: "value" },
  { id: "p25", label: "25% 分位", kind: "value", defaultVisible: false },
  { id: "p75", label: "75% 分位", kind: "value", defaultVisible: false },
  { id: "stdDev", label: "标准差", kind: "value" },
  { id: "iqr", label: "IQR", kind: "value" },
  { id: "percentile", label: "最新值百分位", kind: "percentile" },
  { id: "zScore", label: "Z-score", kind: "zscore" },
  { id: "maxDate", label: "最大值日期", kind: "text" },
  { id: "sessionsSinceMax", label: "距最大值 (观测数)", kind: "count", defaultVisible: false },
  { id: "minDate", label: "最小值日期", kind: "text" },
  { id: "sessionsSinceMin", label: "距最小值 (观测数)", kind: "count", defaultVisible: false },
  { id: "largestGain", label: "最大单日上升", kind: "signed" },
  { id: "largestDrop", label: "最大单日下降", kind: "signed" },
  { id: "meanAbsChange", label: "平均单日绝对变化", kind: "value", defaultVisible: false },
  { id: "positiveShare", label: "正值占比", kind: "percent", defaultVisible: false },
  { id: "skewness", label: "偏度", kind: "ratio" },
  { id: "kurtosis", label: "峰度", kind: "ratio" },
  { id: "autocorrelation", label: "自相关(1)", kind: "ratio" },
  { id: "autocorrelation5", label: "自相关(5)", kind: "ratio", defaultVisible: false },
  { id: "autocorrelation20", label: "自相关(20)", kind: "ratio", defaultVisible: false },
];

function defaultDraft(type) {
  return {
    type,
    instrumentCode: document.getElementById("instrumentCode")?.value.trim() || "US_QQQ",
    chartLane: "1",
    maturityMode: "sliding",
    slidingMaturity: "3M",
    expiry: "",
    strikeKind: "percentage",
    moneynessBasis: "relative_to_forward",
    moneyness: "100",
    delta: "p25.0",
    absoluteStrike: "",
    rvWindow: "63",
    rvAlignment: "trailing",
    volatilityConvention: "bsVol",
    layout: "matrix",
    operandA: "",
    operator: "subtract",
    operandB: "",
    alias: "",
  };
}

const indicatorState = {
  items: [], nextId: 1, discovery: null, draft: defaultDraft("implied_vol"),
  selectedDetailId: null, restorePending: false, chartCount: 1, chartOrder: [1], chartNames: [""],
  chartDragSource: null, hoverSyncing: false, zoomSyncing: false, seriesIndex: new Map(),
  operandSignature: "", hoverDate: null, editingId: null, boards: [], nextBoardId: 1,
  activeBoardId: null, pendingBoardLoad: null, statsColumns: [], columnWidths: {}, dragSource: null,
  dateMode: "sliding", slidingWindow: "1Y", bulkMode: false, bulkSelection: new Set(),
  bulkInstrumentCode: null, bulkEditMode: "underlying",
};

function validIsoDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`));
}
function isValidSlidingWindow(value) {
  const normalized = String(value || "").trim().toUpperCase();
  return normalized === "YTD" || /^[1-9]\d*[DWMY]$/.test(normalized);
}
function normalizeSlidingWindow(value) {
  const normalized = String(value || "").trim().toUpperCase();
  return isValidSlidingWindow(normalized) ? normalized : "1Y";
}
function slidingRange(windowId) {
  const today = isoDate(new Date());
  const normalized = normalizeSlidingWindow(windowId);
  if (normalized === "YTD") return { start: `${today.slice(0, 4)}-01-01`, end: today };
  const match = normalized.match(/^([1-9]\d*)([DWMY])$/);
  const amount = Number(match[1]);
  const unit = match[2];
  const offset = unit === "D" ? { days: -amount }
    : unit === "W" ? { days: -(amount * 7) }
      : unit === "M" ? { months: -amount } : { years: -amount };
  return { start: addCalendar(today, offset), end: today };
}
function syncSlidingRange() {
  if (indicatorState.dateMode !== "sliding") return false;
  const { start, end } = slidingRange(indicatorState.slidingWindow);
  const moved = $("startDate").value !== start || $("endDate").value !== end;
  $("startDate").value = start;
  $("endDate").value = end;
  return moved;
}
function bindDateModeControls() {
  const datalist = $("slidingWindowOptions");
  if (datalist) datalist.innerHTML = SLIDING_WINDOWS.map((window) => `<option value="${window.id}">${escapeHtml(window.label)}</option>`).join("");
  $("dateMode").addEventListener("change", () => {
    indicatorState.dateMode = $("dateMode").value === "fixed" ? "fixed" : "sliding";
    applyDateModeChange();
  });
  const lookback = $("slidingWindow");
  const commitLookback = () => {
    const raw = lookback.value.trim();
    if (!isValidSlidingWindow(raw)) {
      $("dateModeNote").textContent = "Lookback 格式：正整数 + d / w / m / y，例如 52d、2w、3m、3y；也可以输入 YTD。";
      lookback.setAttribute("aria-invalid", "true");
      return;
    }
    lookback.removeAttribute("aria-invalid");
    indicatorState.slidingWindow = normalizeSlidingWindow(raw);
    lookback.value = indicatorState.slidingWindow;
    applyDateModeChange();
  };
  lookback.addEventListener("change", commitLookback);
  lookback.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); commitLookback(); }
  });
}
function applyDateModeChange() {
  const moved = syncSlidingRange();
  renderDateMode();
  persistWorkspace();
  if (moved) invalidateIndicators();
}
function renderDateMode() {
  const sliding = indicatorState.dateMode === "sliding";
  $("dateMode").value = sliding ? "sliding" : "fixed";
  $("slidingWindow").value = indicatorState.slidingWindow;
  $("slidingWindowField").classList.toggle("is-hidden", !sliding);
  for (const id of ["startDate", "endDate"]) {
    $(id).disabled = sliding;
    $(id).classList.toggle("is-derived", sliding);
  }
  $("dateModeNote").textContent = sliding
    ? `${indicatorState.slidingWindow}：按自然日历回溯，结束日期跟随今天。`
    : "固定日期：范围保持不变。日期范围对所有坐标与 indicator 共享；修改后已保存的 indicator 需要刷新才会重新取数。";
}

function bindScopeFields() {
  const instrument = document.querySelector('[data-draft="instrumentCode"]');
  const lane = document.querySelector('[data-draft="chartLane"]');
  const update = (field) => {
    indicatorState.draft[field.dataset.draft] = field.value.trim();
    persistWorkspace();
    renderIndicatorConfig();
  };
  if (instrument) {
    instrument.addEventListener("change", () => update(instrument));
    instrument.addEventListener("input", () => { indicatorState.draft.instrumentCode = instrument.value.trim(); });
  }
  if (lane) lane.addEventListener("change", () => update(lane));
}
function renderScopeFields() {
  const compare = document.querySelector('input[name="queryKind"]:checked')?.value === "compare";
  const lane = $("draftChartLane");
  if (lane) {
    lane.innerHTML = indicatorState.chartOrder.map((value) => `<option value="${value}">${escapeHtml(chartDisplayName(value))}</option>`).join("");
    lane.value = indicatorState.draft.chartLane;
    if (!lane.value) { lane.value = "1"; indicatorState.draft.chartLane = "1"; }
  }
  $("chartLaneField").classList.toggle("is-hidden", !compare);
  $("boardBar").classList.toggle("is-hidden", !compare);
  $("underlyingField").classList.toggle("is-hidden", compare && indicatorState.draft.type === "derived");
}
function syncWorkspaceMode() {
  const compare = document.querySelector('input[name="queryKind"]:checked')?.value === "compare";
  $("indicatorBuilder").classList.toggle("is-hidden", !compare);
  $("surfaceQueryBuilder").classList.toggle("is-hidden", compare);
  $("compareWorkspace").classList.toggle("is-hidden", !compare);
  if (compare) {
    $("welcomeState").classList.add("is-hidden");
    $("loadingState").classList.add("is-hidden");
    $("errorPanel").classList.add("is-hidden");
    renderIndicatorDetails();
  } else {
    $("detailIndicatorField").classList.add("is-hidden");
    if (state.lastResponse?.snapshots) renderResult();
    else { $("resultWorkspace").classList.add("is-hidden"); $("welcomeState").classList.remove("is-hidden"); }
  }
  renderScopeFields();
  refreshWorkspacePanels({ details: false });
}

function normalizeStoredConfig(type, rawConfig, fallbackInstrument) {
  const defaults = defaultDraft(type);
  const normalized = { ...defaults };
  if (!rawConfig || typeof rawConfig !== "object") return normalized;
  for (const key of Object.keys(defaults)) if (typeof rawConfig[key] === typeof defaults[key]) normalized[key] = rawConfig[key];
  normalized.type = type;
  if (!normalized.instrumentCode.trim()) normalized.instrumentCode = String(fallbackInstrument || $("instrumentCode").value).trim();
  const lane = Number(normalized.chartLane);
  normalized.chartLane = String(Number.isInteger(lane) && lane >= 1 && lane <= MAX_CHARTS ? lane : 1);
  return normalized;
}
function serializeItem(item) { return { id: item.id, type: item.type, config: item.config, active: item.active }; }
function restoreWorkspace() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const stored = JSON.parse(raw);
    if (![1, 2].includes(stored?.version) || !Array.isArray(stored.items)) return;
    if (typeof stored.scope?.instrumentCode === "string" && stored.scope.instrumentCode.trim()) $("instrumentCode").value = stored.scope.instrumentCode.trim();
    if (validIsoDate(stored.scope?.startDate)) $("startDate").value = stored.scope.startDate;
    if (validIsoDate(stored.scope?.endDate)) $("endDate").value = stored.scope.endDate;
    indicatorState.dateMode = stored.scope?.dateMode === "sliding" ? "sliding" : "fixed";
    indicatorState.slidingWindow = normalizeSlidingWindow(stored.scope?.slidingWindow);
    const seen = new Set();
    indicatorState.items = stored.items.flatMap((storedItem) => {
      const id = Number(storedItem?.id); const type = storedItem?.type;
      if (!Number.isSafeInteger(id) || id < 1 || seen.has(id) || !Object.hasOwn(TYPE_LABELS, type)) return [];
      seen.add(id);
      return [{ id, type, config: normalizeStoredConfig(type, storedItem.config, stored.scope?.instrumentCode), active: storedItem.active !== false,
        status: type === "derived" ? "ready" : "stale", response: null, request: null, error: null }];
    });
    const largestLane = Math.max(1, ...indicatorState.items.map((item) => Number(item.config.chartLane) || 1));
    indicatorState.chartCount = Math.min(MAX_CHARTS, Math.max(largestLane, Number(stored.chartCount) || 1));
    indicatorState.chartOrder = normalizeChartOrder(stored.chartOrder, indicatorState.chartCount);
    indicatorState.chartNames = normalizeChartNames(stored.chartNames, indicatorState.chartCount);
    indicatorState.draft.instrumentCode = $("instrumentCode").value.trim(); indicatorState.draft.chartLane = "1";
    indicatorState.nextId = Math.max(0, ...indicatorState.items.map((item) => item.id)) + 1;
    const selectedId = Number(stored.selectedDetailId);
    indicatorState.selectedDetailId = indicatorState.items.some((item) => item.id === selectedId) ? selectedId : null;
    const boardId = Number(stored.activeBoardId);
    indicatorState.activeBoardId = indicatorState.boards.some((board) => board.id === boardId) ? boardId : null;
    indicatorState.columnWidths = normalizeColumnWidths(stored.columnWidths);
    indicatorState.restorePending = indicatorState.items.some((item) => item.active);
  } catch (error) { showIndicatorFormError(`无法读取浏览器中保存的 indicators：${error.message}`); }
}
function persistWorkspace() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      version: 2,
      scope: { instrumentCode: $("instrumentCode").value.trim(), startDate: $("startDate").value, endDate: $("endDate").value,
        dateMode: indicatorState.dateMode, slidingWindow: indicatorState.slidingWindow },
      selectedDetailId: indicatorState.selectedDetailId, activeBoardId: indicatorState.activeBoardId,
      chartCount: indicatorState.chartCount, chartOrder: [...indicatorState.chartOrder], chartNames: [...indicatorState.chartNames],
      columnWidths: indicatorState.columnWidths, items: indicatorState.items.map(serializeItem),
    }));
  } catch (error) { showIndicatorFormError(`浏览器无法保存 indicators：${error.message}`); }
  renderBoardState();
}

function normalizeBoardItems(items) {
  const seen = new Set();
  return items.flatMap((item) => {
    const id = Number(item?.id);
    if (!Number.isSafeInteger(id) || id < 1 || seen.has(id) || !Object.hasOwn(TYPE_LABELS, item?.type)) return [];
    seen.add(id);
    return [{ id, type: item.type, config: normalizeStoredConfig(item.type, item.config), active: item.active !== false }];
  });
}
function clampLaneCount(value) { const count = Number(value); return Number.isInteger(count) ? Math.min(MAX_CHARTS, Math.max(1, count)) : 1; }
function normalizeChartOrder(raw, count) {
  const valid = []; const seen = new Set();
  if (Array.isArray(raw)) for (const value of raw) {
    const lane = Number(value); if (!Number.isInteger(lane) || lane < 1 || lane > count || seen.has(lane)) continue;
    seen.add(lane); valid.push(lane);
  }
  for (let lane = 1; lane <= count; lane += 1) if (!seen.has(lane)) valid.push(lane);
  return valid;
}
function normalizeChartNames(raw, count) {
  const source = Array.isArray(raw) ? raw : [];
  return Array.from({ length: count }, (_, index) => {
    const value = typeof source[index] === "string" ? source[index].trim().slice(0, 40) : "";
    return value === `坐标 ${index + 1}` ? "" : value;
  });
}
function chartDisplayName(lane) { return indicatorState.chartNames[lane - 1]?.trim() || `坐标 ${lane}`; }
function normalizeColumnWidths(raw) {
  const widths = {}; if (!raw || typeof raw !== "object") return widths;
  for (const [key, value] of Object.entries(raw)) { const width = Number(value); if (Number.isFinite(width) && width >= MIN_COLUMN_WIDTH) widths[key] = Math.round(width); }
  return widths;
}
function restoreBoards() {
  try {
    const stored = JSON.parse(localStorage.getItem(BOARD_STORAGE_KEY) || "null");
    if (stored?.version !== 1 || !Array.isArray(stored.boards)) return;
    indicatorState.boards = stored.boards.flatMap((board) => {
      const id = Number(board?.id); if (!Number.isSafeInteger(id) || id < 1 || !Array.isArray(board.items)) return [];
      const count = clampLaneCount(board.chartCount);
      return [{ id, name: String(board.name || `板块 ${id}`).slice(0, 60), savedAt: String(board.savedAt || ""),
        startDate: validIsoDate(board.startDate) ? board.startDate : "", endDate: validIsoDate(board.endDate) ? board.endDate : "",
        dateMode: board.dateMode === "sliding" ? "sliding" : "fixed", slidingWindow: normalizeSlidingWindow(board.slidingWindow),
        chartCount: count, chartOrder: normalizeChartOrder(board.chartOrder, count), chartNames: normalizeChartNames(board.chartNames, count),
        columnWidths: normalizeColumnWidths(board.columnWidths), items: normalizeBoardItems(board.items) }];
    });
    indicatorState.nextBoardId = Math.max(0, ...indicatorState.boards.map((board) => board.id)) + 1;
  } catch (error) { showIndicatorFormError(`无法读取已保存的 board：${error.message}`); }
}
function persistBoards() {
  try { localStorage.setItem(BOARD_STORAGE_KEY, JSON.stringify({ version: 1, boards: indicatorState.boards })); }
  catch (error) { showIndicatorFormError(`浏览器无法保存 board：${error.message}`); }
}
function boardById(id) { return indicatorState.boards.find((board) => String(board.id) === String(id)) || null; }
function boardIsDirty() {
  const board = boardById(indicatorState.activeBoardId); if (!board) return false;
  return boardSignature(currentBoardSnapshot(board.name)) !== boardSignature(board);
}
function openingBoardWouldDiscardWork() { return boardIsDirty() || (indicatorState.activeBoardId === null && indicatorState.items.length > 0); }
function currentBoardSnapshot(name) {
  return { name, savedAt: new Date().toISOString(), startDate: $("startDate").value, endDate: $("endDate").value,
    dateMode: indicatorState.dateMode, slidingWindow: indicatorState.slidingWindow, chartCount: indicatorState.chartCount,
    chartOrder: [...indicatorState.chartOrder], chartNames: [...indicatorState.chartNames], columnWidths: { ...indicatorState.columnWidths },
    items: indicatorState.items.map((item) => structuredClone(serializeItem(item))) };
}
function showBoardStatus(message) { $("boardStatus").textContent = message; $("boardStatus").classList.remove("is-hidden"); }
function hideBoardStatus() { $("boardStatus").classList.add("is-hidden"); $("boardStatus").textContent = ""; }
function bindBoardControls() {
  $("saveBoardAsButton").addEventListener("click", saveBoardAs); $("updateBoardButton").addEventListener("click", updateActiveBoard);
  $("deleteBoardButton").addEventListener("click", deleteActiveBoard); $("loadBoardButton").addEventListener("click", () => openBoard($("boardSelect").value));
  $("boardSelect").addEventListener("change", () => { const board = boardById($("boardSelect").value); $("boardName").value = board ? board.name : ""; indicatorState.pendingBoardLoad = null; hideBoardStatus(); renderBoardActions(); });
}
function saveBoardAs() {
  hideBoardStatus(); const name = $("boardName").value.trim();
  if (!name) return showBoardStatus("请先给这个 board 起一个名字。");
  if (!indicatorState.items.length) return showBoardStatus("当前没有 indicator，board 会是空的。");
  const board = { id: indicatorState.nextBoardId++, ...currentBoardSnapshot(name) }; indicatorState.boards.push(board); indicatorState.activeBoardId = board.id;
  persistBoards(); persistWorkspace(); renderBoards();
}
function updateActiveBoard() {
  hideBoardStatus(); const board = boardById(indicatorState.activeBoardId);
  if (!board) return showBoardStatus("当前没有打开的 board；请先用「另存为」创建一个。");
  Object.assign(board, currentBoardSnapshot($("boardName").value.trim() || board.name)); persistBoards(); renderBoards(); showBoardStatus(`已更新「${board.name}」。`);
}
function deleteActiveBoard() {
  hideBoardStatus(); const board = boardById($("boardSelect").value); if (!board) return showBoardStatus("请先在下拉框中选择要删除的 board。");
  indicatorState.boards = indicatorState.boards.filter((candidate) => candidate.id !== board.id); if (indicatorState.activeBoardId === board.id) indicatorState.activeBoardId = null;
  persistBoards(); persistWorkspace(); renderBoards();
}
function openBoard(id) {
  hideBoardStatus(); hideIndicatorFormError(); const board = boardById(id); if (!board) return showBoardStatus("请先在下拉框中选择一个 board。");
  if (openingBoardWouldDiscardWork() && String(indicatorState.pendingBoardLoad) !== String(board.id)) {
    indicatorState.pendingBoardLoad = board.id; const active = boardById(indicatorState.activeBoardId);
    return showBoardStatus(active ? `「${active.name}」有未保存的修改，载入会丢弃它们。先点「更新当前 board」保存，或再点一次「载入」确认。`
      : "当前工作区还没有保存为 board，载入会覆盖它。先点「另存为新 board」保存，或再点一次「载入」确认。");
  }
  indicatorState.pendingBoardLoad = null; indicatorState.dateMode = board.dateMode; indicatorState.slidingWindow = board.slidingWindow;
  if (board.startDate) $("startDate").value = board.startDate; if (board.endDate) $("endDate").value = board.endDate;
  syncSlidingRange(); renderDateMode();
  indicatorState.items = board.items.map((item) => ({ id: item.id, type: item.type, config: structuredClone(item.config), active: item.active,
    status: item.type === "derived" ? "ready" : "stale", response: null, request: null, error: null }));
  const largestLane = Math.max(1, ...indicatorState.items.map((item) => Number(item.config.chartLane) || 1));
  indicatorState.chartCount = Math.min(MAX_CHARTS, Math.max(largestLane, board.chartCount)); indicatorState.chartOrder = normalizeChartOrder(board.chartOrder, indicatorState.chartCount);
  indicatorState.chartNames = normalizeChartNames(board.chartNames, indicatorState.chartCount); indicatorState.nextId = Math.max(0, ...indicatorState.items.map((item) => item.id)) + 1;
  indicatorState.activeBoardId = board.id; indicatorState.selectedDetailId = null; indicatorState.editingId = null; indicatorState.hoverDate = null; indicatorState.draft.chartLane = "1";
  if (indicatorState.bulkMode) toggleBulkMode(false); indicatorState.columnWidths = { ...board.columnWidths };
  persistWorkspace(); renderBoards(); renderScopeFields(); renderIndicatorConfig(); renderBuilderMode(); refreshWorkspacePanels(); refreshActiveIndicators();
}

function itemById(id) { return indicatorState.items.find((item) => String(item.id) === String(id)) || null; }
function dependencyClosure(id) {
  const blocked = new Set([Number(id)]); let grew = true;
  while (grew) { grew = false; for (const item of indicatorState.items) {
    if (item.type !== "derived" || blocked.has(item.id)) continue;
    if ([item.config.operandA, item.config.operandB].map(Number).some((reference) => blocked.has(reference))) { blocked.add(item.id); grew = true; }
  }}
  return blocked;
}
function operandCandidates() { if (indicatorState.editingId === null) return indicatorState.items; const blocked = dependencyClosure(indicatorState.editingId); return indicatorState.items.filter((item) => !blocked.has(item.id)); }
function ensureDerivedDefaults(draft) {
  const ids = operandCandidates().map((item) => String(item.id));
  if (!ids.includes(draft.operandA)) draft.operandA = ids[0] || "";
  if (!ids.includes(draft.operandB)) draft.operandB = ids[1] || ids[0] || "";
  if (!Object.hasOwn(OPERATOR_SYMBOLS, draft.operator)) draft.operator = "subtract";
}
function initialStatus(type) { return type === "derived" ? "ready" : "queued"; }
function submitIndicator() {
  hideIndicatorFormError();
  try { validateScope(indicatorState.draft); validateDraft(indicatorState.draft); }
  catch (error) { showIndicatorFormError(error.message); return; }
  if (indicatorState.editingId !== null) return applyIndicatorEdit();
  const item = { id: indicatorState.nextId++, type: indicatorState.draft.type, config: structuredClone(indicatorState.draft), active: true,
    status: initialStatus(indicatorState.draft.type), response: null, request: null, error: null };
  indicatorState.items.push(item); persistWorkspace();
  if (item.type === "derived") { refreshWorkspacePanels(); fetchMissingDependencies(); return; }
  indicatorState.selectedDetailId = item.id; renderSavedIndicators(); fetchIndicator(item);
}
function applyIndicatorEdit() {
  const item = itemById(indicatorState.editingId); if (!item) { indicatorState.editingId = null; renderBuilderMode(); return; }
  item.type = indicatorState.draft.type; item.config = structuredClone(indicatorState.draft); item.status = initialStatus(item.type); item.response = null; item.request = null; item.error = null;
  indicatorState.editingId = null; persistWorkspace(); renderBuilderMode();
  if (item.type === "derived") { refreshWorkspacePanels(); fetchMissingDependencies(); return; }
  fetchIndicator(item);
}
function startEditing(id) {
  const item = itemById(id); if (!item) return; hideIndicatorFormError(); indicatorState.editingId = item.id; indicatorState.draft = structuredClone(item.config); indicatorState.draft.type = item.type;
  indicatorState.discovery = null; $("indicatorType").value = item.type; if (item.type !== "derived") $("instrumentCode").value = item.config.instrumentCode;
  renderScopeFields(); renderIndicatorConfig(); renderBuilderMode(); renderSavedIndicators(); $("indicatorBuilder").scrollIntoView({ behavior: "smooth", block: "start" });
}
function cancelEditing() {
  indicatorState.editingId = null; hideIndicatorFormError(); const draft = defaultDraft($("indicatorType").value); draft.instrumentCode = $("instrumentCode").value.trim();
  indicatorState.draft = draft; indicatorState.discovery = null; renderScopeFields(); renderIndicatorConfig(); renderBuilderMode(); renderSavedIndicators();
}
function duplicateIndicator(id) {
  const source = itemById(id); if (!source) return; hideIndicatorFormError();
  const copy = { id: indicatorState.nextId++, type: source.type, config: structuredClone(source.config), active: source.active,
    status: initialStatus(source.type), response: null, request: null, error: null };
  indicatorState.items.splice(indicatorState.items.indexOf(source) + 1, 0, copy); persistWorkspace(); refreshWorkspacePanels({ details: false });
  if (copy.type !== "derived" && copy.active) fetchIndicator(copy);
}

function bulkTargetIds() {
  const selected = new Set(indicatorState.bulkSelection); let grew = true;
  while (grew) { grew = false; for (const item of indicatorState.items) {
    if (item.type !== "derived" || !selected.has(item.id)) continue;
    for (const reference of [item.config.operandA, item.config.operandB]) { const operand = itemById(reference); if (operand && !selected.has(operand.id)) { selected.add(operand.id); grew = true; } }
  }}
  return selected;
}
function toggleBulkMode(on) {
  indicatorState.bulkMode = on ?? !indicatorState.bulkMode; indicatorState.bulkSelection = new Set(); indicatorState.bulkInstrumentCode = null; indicatorState.bulkEditMode = "underlying";
  hideIndicatorFormError(); setBulkNote(""); if ($("bulkInstrumentCode")) $("bulkInstrumentCode").value = ""; hideBulkInstrumentResults();
  $("bulkBar").classList.toggle("is-hidden", !indicatorState.bulkMode); $("bulkModeButton").classList.toggle("is-on", indicatorState.bulkMode);
  setBulkEditMode("underlying"); syncBulkInstrumentButtons(); renderBulkMaturityControls(); renderSavedIndicators();
}
function setBulkSelection(id, selected) { if (selected) indicatorState.bulkSelection.add(id); else indicatorState.bulkSelection.delete(id); setBulkNote(""); renderSavedIndicators(); }
function setBulkNote(message, tone = "") { const note = $("bulkNote"); if (!note) return; note.textContent = message; note.className = `bulk-note ${tone}`.trim(); }
function syncBulkInstrumentButtons() { const enabled = Boolean(indicatorState.bulkInstrumentCode) && bulkTargetIds().size > 0; if ($("bulkMoveButton")) $("bulkMoveButton").disabled = !enabled; if ($("bulkCopyButton")) $("bulkCopyButton").disabled = !enabled; }
function clearBulkInstrumentSelection() {
  const typed = $("bulkInstrumentCode")?.value.trim() || ""; if (typed === indicatorState.bulkInstrumentCode) return; indicatorState.bulkInstrumentCode = null; setBulkNote("");
  if ($("bulkInstrumentHelp")) $("bulkInstrumentHelp").textContent = "输入代码或名称后按 Enter 或点 ⌕ 搜索，再从结果里点选。"; syncBulkInstrumentButtons();
}
function handleBulkInstrumentKeydown(event) { if (event.key === "Enter") { event.preventDefault(); searchBulkInstruments(); } else if (event.key === "Escape") hideBulkInstrumentResults(); }
async function searchBulkInstruments() {
  const query = $("bulkInstrumentCode")?.value.trim() || "";
  if (!query) { indicatorState.bulkInstrumentCode = null; hideBulkInstrumentResults(); syncBulkInstrumentButtons(); return setBulkNote("请输入目标标的的代码或名称。", "is-error"); }
  if ($("bulkInstrumentHelp")) $("bulkInstrumentHelp").textContent = "正在搜索 instrument catalogue…"; setBulkNote("");
  try {
    const response = await apiFetch(`${state.capabilities.endpoints.instruments}?q=${encodeURIComponent(query)}&type=equity&maxResults=50`); const data = await response.json(); const instruments = data.instruments || [];
    const exact = instruments.find((item) => String(item.code || "").toLocaleLowerCase() === query.toLocaleLowerCase()); if (exact) return selectBulkInstrument(exact.code);
    renderBulkInstrumentResults(instruments); if ($("bulkInstrumentHelp")) $("bulkInstrumentHelp").textContent = data.hasMore ? `匹配 ${data.matchedCount} 项，仅显示前 ${data.returnedCount} 项；请缩小关键词后重新搜索。` : `匹配 ${data.matchedCount} 项；点击下方结果即可选用。`;
  } catch (error) { indicatorState.bulkInstrumentCode = null; hideBulkInstrumentResults(); syncBulkInstrumentButtons(); if ($("bulkInstrumentHelp")) $("bulkInstrumentHelp").textContent = `搜索失败：${apiErrorSummary(error, "instrument catalogue 搜索失败")}`; }
}
function renderBulkInstrumentResults(instruments) {
  const box = $("bulkInstrumentResults"); if (!box) return;
  if (!instruments.length) { box.innerHTML = '<p class="instrument-empty">没有匹配的 instrument。</p>'; box.classList.remove("is-hidden"); return; }
  box.innerHTML = instruments.map((item) => { const meta = [item.type, item.marketName, item.currencyCode].filter(Boolean).join(" · "); return `<button type="button" class="instrument-result" role="option" data-bulk-instrument-code="${escapeHtml(item.code)}"><strong>${escapeHtml(item.code)}</strong><span>${escapeHtml(item.companyName || item.bbgCode || "")}</span>${meta ? `<em>${escapeHtml(meta)}</em>` : ""}</button>`; }).join(""); box.classList.remove("is-hidden");
}
function handleBulkInstrumentResultClick(event) { const choice = event.target.closest("[data-bulk-instrument-code]"); if (choice) selectBulkInstrument(choice.dataset.bulkInstrumentCode); }
function selectBulkInstrument(code) { if ($("bulkInstrumentCode")) $("bulkInstrumentCode").value = code; indicatorState.bulkInstrumentCode = code; hideBulkInstrumentResults(); if ($("bulkInstrumentHelp")) $("bulkInstrumentHelp").textContent = `已选择 ${code}。`; setBulkNote(""); syncBulkInstrumentButtons(); }
function hideBulkInstrumentResults() { const box = $("bulkInstrumentResults"); if (!box) return; box.classList.add("is-hidden"); box.innerHTML = ""; }
function setBulkEditMode(mode) {
  indicatorState.bulkEditMode = mode === "maturity" ? "maturity" : "underlying"; const maturity = indicatorState.bulkEditMode === "maturity";
  $("bulkUnderlyingPanel")?.classList.toggle("is-hidden", maturity); $("bulkMaturityPanel")?.classList.toggle("is-hidden", !maturity);
  $("bulkUnderlyingTab")?.classList.toggle("is-active", !maturity); $("bulkMaturityTab")?.classList.toggle("is-active", maturity); setBulkNote(""); if (maturity) renderBulkMaturityControls();
}
function bulkMaturityTargetIds() {
  const selected = new Set(); for (const id of indicatorState.bulkSelection) { const item = itemById(id); if (item && ["derived", "implied_vol", "forward"].includes(item.type)) selected.add(item.id); }
  let grew = true; while (grew) { grew = false; for (const item of indicatorState.items) {
    if (item.type !== "derived" || !selected.has(item.id)) continue;
    for (const reference of [item.config.operandA, item.config.operandB]) { const operand = itemById(reference); if (operand && !selected.has(operand.id)) { selected.add(operand.id); grew = true; } }
  }} return selected;
}
function bulkMaturityItems() { const ids = bulkMaturityTargetIds(); return indicatorState.items.filter((item) => ids.has(item.id) && ["implied_vol", "forward"].includes(item.type)); }
function bulkMaturitySupportedTenors(items) { const hasDelta = items.some((item) => item.type === "implied_vol" && item.config.strikeKind === "delta"); return hasDelta ? state.capabilities?.deltaMaturities || [] : state.capabilities?.slidingMaturities || []; }
function renderBulkMaturityControls() {
  const mode = $("bulkMaturityMode")?.value === "fixed" ? "fixed" : "sliding"; $("bulkSlidingMaturityField")?.classList.toggle("is-hidden", mode !== "sliding"); $("bulkFixedMaturityField")?.classList.toggle("is-hidden", mode !== "fixed");
  const items = bulkMaturityItems(); const select = $("bulkSlidingMaturity");
  if (select && mode === "sliding") { const values = bulkMaturitySupportedTenors(items); const current = select.value; select.innerHTML = values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join(""); select.value = values.includes(current) ? current : values.includes("3M") ? "3M" : values[0] || ""; }
  if ($("bulkMaturityHelp")) { const ignored = [...indicatorState.bulkSelection].map(itemById).filter((item) => item && ["spot", "realized_vol"].includes(item.type)).length; $("bulkMaturityHelp").textContent = `将修改 ${items.length} 个 IV / Forward。Sliding 与 Fixed date 支持批量；Fixed date 会按精确日期请求，坐标不存在时允许后端返回 NO_DATA，不做最近期限替代。Listed expiry 暂不作为批量目标。${ignored ? ` 另有 ${ignored} 个直接选中的 Spot/RV 没有 option tenor，会忽略。` : ""}`; }
  syncBulkMaturityButtons();
}
function syncBulkMaturityButtons() { const items = bulkMaturityItems(); const mode = $("bulkMaturityMode")?.value === "fixed" ? "fixed" : "sliding"; const value = mode === "sliding" ? $("bulkSlidingMaturity")?.value || "" : $("bulkFixedMaturity")?.value || ""; const enabled = items.length > 0 && Boolean(value); if ($("bulkMaturityMoveButton")) $("bulkMaturityMoveButton").disabled = !enabled; if ($("bulkMaturityCopyButton")) $("bulkMaturityCopyButton").disabled = !enabled; }
function bulkMaturityCompatibility(items, mode, value) {
  if (!items.length) return "所选项里没有 IV 或 Forward 可以修改期限。";
  if (mode === "fixed") { if (!validIsoDate(value)) return "请选择合法的 Fixed maturity date。"; const delta = items.filter((item) => item.type === "implied_vol" && item.config.strikeKind === "delta"); return delta.length ? `有 ${delta.length} 个 Delta IV；当前数据契约只支持 Delta + Sliding maturity，不能批量改成 Fixed date。` : null; }
  const supported = bulkMaturitySupportedTenors(items); if (!supported.includes(value)) return `当前所选指标不支持 Sliding tenor ${value || "(空)"}。`;
  const absolute = items.filter((item) => item.type === "implied_vol" && item.config.strikeKind === "absolute"); return absolute.length ? `有 ${absolute.length} 个 Absolute-strike IV；当前数据契约不支持 Absolute strike + Sliding maturity。` : null;
}
function applyMaturityToItem(item, mode, value) { item.config.maturityMode = mode; if (mode === "sliding") { item.config.slidingMaturity = value; item.config.expiry = ""; } else item.config.expiry = value; item.status = initialStatus(item.type); item.response = null; item.request = null; item.error = null; }
function applyBulkMaturity({ copy }) {
  hideIndicatorFormError(); const mode = $("bulkMaturityMode")?.value === "fixed" ? "fixed" : "sliding"; const value = mode === "sliding" ? $("bulkSlidingMaturity")?.value || "" : $("bulkFixedMaturity")?.value || ""; const items = bulkMaturityItems(); const problem = bulkMaturityCompatibility(items, mode, value); if (problem) return setBulkNote(problem, "is-error");
  const outcome = copy ? bulkCopyMaturity(mode, value) : bulkMoveMaturity(items, mode, value); persistWorkspace(); refreshWorkspacePanels(); fetchMissingDependencies(); renderBulkMaturityControls(); setBulkNote(outcome);
}
function bulkMoveMaturity(items, mode, value) { const renamed = items.filter((item) => indicatorAlias(item)).length; for (const item of items) applyMaturityToItem(item, mode, value); const label = mode === "fixed" ? `Fixed ${value}` : `Sliding ${value}`; const notes = [`已把 ${items.length} 个 IV / Forward 换成 ${label}。`]; if (renamed) notes.push(`其中 ${renamed} 个保留了原有别名，如不再合适请双击列头改名。`); notes.push(...duplicateWarning(items)); return notes.join(""); }
function bulkCopyMaturity(mode, value) {
  const targetIds = bulkMaturityTargetIds(); const targets = indicatorState.items.filter((item) => targetIds.has(item.id)); const maturityIds = new Set(targets.filter((item) => ["implied_vol", "forward"].includes(item.type)).map((item) => item.id)); const idMap = new Map();
  const copies = targets.map((source) => { const copy = { id: indicatorState.nextId++, type: source.type, config: structuredClone(source.config), active: source.active, status: initialStatus(source.type), response: null, request: null, error: null }; copy.config.alias = ""; if (maturityIds.has(source.id)) applyMaturityToItem(copy, mode, value); idMap.set(source.id, copy.id); return copy; });
  for (const copy of copies) if (copy.type === "derived") for (const key of ["operandA", "operandB"]) { const mapped = idMap.get(Number(copy.config[key])); if (mapped !== undefined) copy.config[key] = mapped; }
  indicatorState.items.push(...copies); const maturityCount = copies.filter((copy) => ["implied_vol", "forward"].includes(copy.type)).length; const derivedCount = copies.filter((copy) => copy.type === "derived").length; const label = mode === "fixed" ? `Fixed ${value}` : `Sliding ${value}`; const notes = [`已复制 ${copies.length} 个指标，其中 ${maturityCount} 个 IV / Forward 改为 ${label}${derivedCount ? `，${derivedCount} 个运算指标已接到复制出的操作数` : ""}。`]; notes.push(...duplicateWarning(copies)); return notes.join("");
}
function applyBulkInstrument({ copy }) {
  hideIndicatorFormError(); const code = indicatorState.bulkInstrumentCode; if (!code) return setBulkNote("请先搜索并选择目标标的。", "is-error");
  const targets = indicatorState.items.filter((item) => bulkTargetIds().has(item.id)); const repointable = targets.filter((item) => item.type !== "derived"); if (!repointable.length) return setBulkNote("所选项里没有可以改标的的基础指标。", "is-error");
  const outcome = copy ? bulkCopy(targets, code) : bulkMove(repointable, code); persistWorkspace(); refreshWorkspacePanels(); fetchMissingDependencies(); setBulkNote(outcome);
}
function bulkMove(repointable, code) { const renamed = repointable.filter((item) => indicatorAlias(item)).length; for (const item of repointable) { item.config.instrumentCode = code; item.status = initialStatus(item.type); item.response = null; item.request = null; item.error = null; } const notes = [`已把 ${repointable.length} 个指标换成 ${code}。`]; if (renamed) notes.push(`其中 ${renamed} 个保留了原有别名，如不再合适请双击列头改名。`); notes.push(...duplicateWarning(repointable)); return notes.join(""); }
function bulkCopy(targets, code) {
  const idMap = new Map(); const copies = targets.map((source) => { const copy = { id: indicatorState.nextId++, type: source.type, config: structuredClone(source.config), active: source.active, status: initialStatus(source.type), response: null, request: null, error: null }; copy.config.alias = ""; if (copy.type !== "derived") copy.config.instrumentCode = code; idMap.set(source.id, copy.id); return copy; });
  for (const copy of copies) if (copy.type === "derived") for (const key of ["operandA", "operandB"]) { const mapped = idMap.get(Number(copy.config[key])); if (mapped !== undefined) copy.config[key] = mapped; }
  indicatorState.items.push(...copies); const derived = copies.filter((copy) => copy.type === "derived").length; const notes = [`已按 ${code} 复制出 ${copies.length} 个指标${derived ? `（含 ${derived} 个运算指标，已接到复制出的操作数上）` : ""}。`]; notes.push(...duplicateWarning(copies)); return notes.join("");
}
function duplicateWarning(changed) { const changedIds = new Set(changed.map((item) => item.id)); const others = indicatorState.items.filter((item) => !changedIds.has(item.id)).map(coordinateSignature); const clashes = changed.filter((item) => others.includes(coordinateSignature(item))).length; return clashes ? [`有 ${clashes} 个与已存在的指标坐标完全相同，图上会出现重合的线。`] : []; }
function handleBulkBarClick(event) {
  if (event.target.closest("[data-bulk-exit]")) return toggleBulkMode(false);
  if (event.target.closest("[data-bulk-none]")) { indicatorState.bulkSelection = new Set(); setBulkNote(""); return renderSavedIndicators(); }
  if (event.target.closest("[data-bulk-all]")) { indicatorState.bulkSelection = new Set(indicatorState.items.filter((item) => item.type !== "derived").map((item) => item.id)); setBulkNote(""); renderSavedIndicators(); }
}

function restoreStatsColumns() {
  let stored = []; try { const raw = JSON.parse(localStorage.getItem(STATS_STORAGE_KEY) || "null"); if (raw?.version === 1 && Array.isArray(raw.columns)) stored = raw.columns; } catch (error) { showIndicatorFormError(`无法读取统计列设置：${error.message}`); }
  const known = new Map(STAT_COLUMNS.map((column) => [column.id, column])); const ordered = []; const seen = new Set();
  for (const entry of stored) { if (!known.has(entry?.id) || seen.has(entry.id)) continue; seen.add(entry.id); ordered.push({ id: entry.id, visible: entry.visible !== false }); }
  for (const column of STAT_COLUMNS) if (!seen.has(column.id)) ordered.push({ id: column.id, visible: column.defaultVisible !== false }); indicatorState.statsColumns = ordered;
}
function persistStatsColumns() { try { localStorage.setItem(STATS_STORAGE_KEY, JSON.stringify({ version: 1, columns: indicatorState.statsColumns })); } catch (error) { showIndicatorFormError(`浏览器无法保存统计列设置：${error.message}`); } }
function visibleStatsColumns() { const known = new Map(STAT_COLUMNS.map((column) => [column.id, column])); return indicatorState.statsColumns.filter((entry) => entry.visible).map((entry) => known.get(entry.id)); }
function moveWithin(list, fromIndex, toIndex) { const [moved] = list.splice(fromIndex, 1); list.splice(toIndex, 0, moved); }
function showIndicatorFormError(message) { $("indicatorFormError").textContent = message; $("indicatorFormError").classList.remove("is-hidden"); }
function hideIndicatorFormError() { $("indicatorFormError").classList.add("is-hidden"); }
