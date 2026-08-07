"use strict";

(() => {
  const STORAGE_KEY = "volcurve.compare.workspace.v1";
  const BOARD_STORAGE_KEY = "volcurve.compare.boards.v1";
  const STATS_STORAGE_KEY = "volcurve.compare.statscolumns.v1";
  const MAX_CHARTS = 5;
  const indicatorState = {
    items: [],
    nextId: 1,
    discovery: null,
    draft: defaultDraft("implied_vol"),
    selectedDetailId: null,
    restorePending: false,
    chartCount: 1,
    hoverSyncing: false,
    zoomSyncing: false,
    seriesIndex: new Map(),
    operandSignature: "",
    hoverDate: null,
    editingId: null,
    boards: [],
    nextBoardId: 1,
    activeBoardId: null,
    pendingBoardLoad: null,
    statsColumns: [],
    columnWidths: {},
    dragSource: null,
    dateMode: "sliding",
    slidingWindow: "1Y",
  };

  // A sliding range is re-derived from today every time the workspace or a board opens,
  // so reopening tomorrow pulls tomorrow's data without touching the configuration.
  const SLIDING_WINDOWS = [
    { id: "1M", label: "近 1 个月", months: 1 },
    { id: "3M", label: "近 3 个月", months: 3 },
    { id: "6M", label: "近 6 个月", months: 6 },
    { id: "YTD", label: "年初至今", ytd: true },
    { id: "1Y", label: "近 1 年", years: 1 },
    { id: "2Y", label: "近 2 年", years: 2 },
    { id: "3Y", label: "近 3 年", years: 3 },
    { id: "5Y", label: "近 5 年", years: 5 },
    { id: "10Y", label: "近 10 年", years: 10 },
  ];

  const STATS_LABEL_COLUMN = "__label__";
  const DEFAULT_LABEL_WIDTH = 190;
  const DEFAULT_SERIES_WIDTH = 150;
  const MIN_COLUMN_WIDTH = 80;

  const TYPE_LABELS = {
    implied_vol: "Implied volatility",
    realized_vol: "Realized volatility",
    spot: "Spot · 原始未复权",
    forward: "Forward",
    derived: "Derived · 指标运算",
  };
  const OPERATOR_SYMBOLS = { add: "＋", subtract: "−", multiply: "×", divide: "÷" };
  const VOL_TYPES = new Set(["implied_vol", "realized_vol"]);
  const PRICE_TYPES = new Set(["spot", "forward"]);
  const PALETTE = ["#0f7554", "#3557a4", "#d66a2d", "#8c6bb1", "#bf3d5d", "#4e8f9c", "#8e7b28"];

  // A board is a named, reloadable page: which indicators exist, how they are spread
  // across lanes and over which dates. It stores configuration only — never responses —
  // so opening one always re-requests the data.
  // defaultVisible: false marks the less commonly used statistics — longer windows that
  // need more history than most ranges have, and secondary metrics most users won't
  // reach for day to day. They stay one click away in 统计项设置, just off by default.
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
    };
  }

  function initIndicatorBuilder() {
    $("indicatorType").addEventListener("change", (event) => {
      const next = defaultDraft(event.target.value);
      next.instrumentCode = indicatorState.draft.instrumentCode;
      next.chartLane = indicatorState.draft.chartLane;
      indicatorState.draft = next;
      indicatorState.discovery = null;
      renderScopeFields();
      renderIndicatorConfig();
    });
    $("addIndicatorButton").addEventListener("click", submitIndicator);
    $("cancelEditButton").addEventListener("click", cancelEditing);
    $("refreshIndicatorsButton").addEventListener("click", refreshActiveIndicators);
    $("addChartButton").addEventListener("click", addChartLane);
    $("indicatorCharts").addEventListener("click", handleChartStackClick);
    $("savedIndicators").addEventListener("change", handleSavedIndicatorChange);
    $("savedIndicators").addEventListener("click", handleSavedIndicatorClick);
    $("detailIndicatorSelect").addEventListener("change", (event) => {
      indicatorState.selectedDetailId = Number(event.target.value);
      persistWorkspace();
      renderIndicatorDetails();
    });
    for (const id of ["startDate", "endDate"]) {
      $(id).addEventListener("change", invalidateIndicators);
    }
    bindDateModeControls();
    bindScopeFields();
    bindBoardControls();
    bindStatsColumnControls();
    document.querySelectorAll('input[name="queryKind"]').forEach((input) => {
      input.addEventListener("change", syncWorkspaceMode);
    });
    window.addEventListener("volcurve:capabilities", () => {
      renderIndicatorConfig();
      refreshWorkspacePanels({ details: false });
      if (indicatorState.restorePending) {
        indicatorState.restorePending = false;
        refreshActiveIndicators();
      }
    });
    restoreStatsColumns();
    restoreBoards();
    restoreWorkspace();
    syncSlidingRange();
    renderDateMode();
    syncWorkspaceMode();
    renderIndicatorConfig();
    renderBuilderMode();
    renderStatsColumnConfig();
    renderBoards();
  }

  function bindDateModeControls() {
    $("slidingWindow").innerHTML = SLIDING_WINDOWS
      .map((window) => `<option value="${window.id}">${escapeHtml(window.label)}</option>`).join("");
    $("dateMode").addEventListener("change", () => {
      indicatorState.dateMode = $("dateMode").value === "fixed" ? "fixed" : "sliding";
      applyDateModeChange();
    });
    $("slidingWindow").addEventListener("change", () => {
      indicatorState.slidingWindow = $("slidingWindow").value;
      applyDateModeChange();
    });
  }

  function applyDateModeChange() {
    const moved = syncSlidingRange();
    renderDateMode();
    persistWorkspace();
    if (moved) invalidateIndicators();
  }

  function slidingRange(windowId) {
    const today = isoDate(new Date());
    const window = SLIDING_WINDOWS.find((entry) => entry.id === windowId)
      || SLIDING_WINDOWS.find((entry) => entry.id === "1Y");
    if (window.ytd) return { start: `${today.slice(0, 4)}-01-01`, end: today };
    return {
      start: addCalendar(today, { years: -(window.years || 0), months: -(window.months || 0) }),
      end: today,
    };
  }

  // Writes today's window into the date inputs. Returns whether the range actually moved,
  // so callers only invalidate loaded series when the dates really changed.
  function syncSlidingRange() {
    if (indicatorState.dateMode !== "sliding") return false;
    const { start, end } = slidingRange(indicatorState.slidingWindow);
    const moved = $("startDate").value !== start || $("endDate").value !== end;
    $("startDate").value = start;
    $("endDate").value = end;
    return moved;
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
    const label = SLIDING_WINDOWS.find((entry) => entry.id === indicatorState.slidingWindow)?.label || "近 1 年";
    $("dateModeNote").textContent = sliding
      ? `${label}：结束日期跟随今天，每次打开页面、载入 board 或点「刷新激活项」都会重新算到当天，因此拿到的是最新数据。`
      : "固定日期：范围保持不变，重新打开也只取这段区间。日期范围对所有坐标与 indicator 共享；修改后已保存的 indicator 需要刷新才会重新取数。";
  }

  // The underlying and the target chart lane live above the indicator builder so a new
  // indicator is described top-down: date range → underlying + lane → indicator definition.
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
      lane.innerHTML = Array.from({ length: indicatorState.chartCount }, (_, index) => index + 1)
        .map((value) => `<option value="${value}">坐标 ${value}</option>`).join("");
      lane.value = indicatorState.draft.chartLane;
      if (!lane.value) {
        lane.value = "1";
        indicatorState.draft.chartLane = "1";
      }
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
      else {
        $("resultWorkspace").classList.add("is-hidden");
        $("welcomeState").classList.remove("is-hidden");
      }
    }
    renderScopeFields();
    refreshWorkspacePanels({ details: false });
  }

  function restoreWorkspace() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const stored = JSON.parse(raw);
      if (![1, 2].includes(stored?.version) || !Array.isArray(stored.items)) return;
      if (typeof stored.scope?.instrumentCode === "string" && stored.scope.instrumentCode.trim()) {
        $("instrumentCode").value = stored.scope.instrumentCode.trim();
      }
      if (validIsoDate(stored.scope?.startDate)) $("startDate").value = stored.scope.startDate;
      if (validIsoDate(stored.scope?.endDate)) $("endDate").value = stored.scope.endDate;
      // A workspace saved before sliding ranges existed keeps its explicit dates; only a
      // brand new workspace starts on the sliding default.
      indicatorState.dateMode = stored.scope?.dateMode === "sliding" ? "sliding" : "fixed";
      indicatorState.slidingWindow = normalizeSlidingWindow(stored.scope?.slidingWindow);
      const seen = new Set();
      indicatorState.items = stored.items.flatMap((storedItem) => {
        const id = Number(storedItem?.id);
        const type = storedItem?.type;
        if (!Number.isSafeInteger(id) || id < 1 || seen.has(id) || !Object.hasOwn(TYPE_LABELS, type)) return [];
        seen.add(id);
        return [{
          id,
          type,
          config: normalizeStoredConfig(type, storedItem.config, stored.scope?.instrumentCode),
          active: storedItem.active !== false,
          status: type === "derived" ? "ready" : "stale",
          response: null,
          request: null,
          error: null,
        }];
      });
      const largestLane = Math.max(1, ...indicatorState.items.map((item) => Number(item.config.chartLane) || 1));
      indicatorState.chartCount = Math.min(MAX_CHARTS, Math.max(largestLane, Number(stored.chartCount) || 1));
      indicatorState.draft.instrumentCode = $("instrumentCode").value.trim();
      indicatorState.draft.chartLane = "1";
      indicatorState.nextId = Math.max(0, ...indicatorState.items.map((item) => item.id)) + 1;
      const selectedId = Number(stored.selectedDetailId);
      indicatorState.selectedDetailId = indicatorState.items.some((item) => item.id === selectedId) ? selectedId : null;
      const boardId = Number(stored.activeBoardId);
      indicatorState.activeBoardId = indicatorState.boards.some((board) => board.id === boardId) ? boardId : null;
      indicatorState.columnWidths = normalizeColumnWidths(stored.columnWidths);
      indicatorState.restorePending = indicatorState.items.some((item) => item.active);
    } catch (error) {
      showIndicatorFormError(`无法读取浏览器中保存的 indicators：${error.message}`);
    }
  }

  function normalizeStoredConfig(type, rawConfig, fallbackInstrument) {
    const defaults = defaultDraft(type);
    const normalized = { ...defaults };
    if (!rawConfig || typeof rawConfig !== "object") return normalized;
    for (const key of Object.keys(defaults)) {
      if (typeof rawConfig[key] === typeof defaults[key]) normalized[key] = rawConfig[key];
    }
    normalized.type = type;
    if (!normalized.instrumentCode.trim()) normalized.instrumentCode = String(fallbackInstrument || $("instrumentCode").value).trim();
    const lane = Number(normalized.chartLane);
    normalized.chartLane = String(Number.isInteger(lane) && lane >= 1 && lane <= MAX_CHARTS ? lane : 1);
    return normalized;
  }

  function persistWorkspace() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        version: 2,
        scope: {
          instrumentCode: $("instrumentCode").value.trim(),
          startDate: $("startDate").value,
          endDate: $("endDate").value,
          dateMode: indicatorState.dateMode,
          slidingWindow: indicatorState.slidingWindow,
        },
        selectedDetailId: indicatorState.selectedDetailId,
        activeBoardId: indicatorState.activeBoardId,
        chartCount: indicatorState.chartCount,
        columnWidths: indicatorState.columnWidths,
        items: indicatorState.items.map(serializeItem),
      }));
    } catch (error) {
      showIndicatorFormError(`浏览器无法保存 indicators：${error.message}`);
    }
    // Every mutation routes through here, so this is where the board's unsaved marker
    // is kept honest.
    renderBoardState();
  }

  function serializeItem(item) {
    return { id: item.id, type: item.type, config: item.config, active: item.active };
  }

  // ---------------------------------------------------------------- saved boards

  function restoreBoards() {
    try {
      const stored = JSON.parse(localStorage.getItem(BOARD_STORAGE_KEY) || "null");
      if (stored?.version !== 1 || !Array.isArray(stored.boards)) return;
      indicatorState.boards = stored.boards.flatMap((board) => {
        const id = Number(board?.id);
        if (!Number.isSafeInteger(id) || id < 1 || !Array.isArray(board.items)) return [];
        return [{
          id,
          name: String(board.name || `板块 ${id}`).slice(0, 60),
          savedAt: String(board.savedAt || ""),
          startDate: validIsoDate(board.startDate) ? board.startDate : "",
          endDate: validIsoDate(board.endDate) ? board.endDate : "",
          dateMode: board.dateMode === "sliding" ? "sliding" : "fixed",
          slidingWindow: normalizeSlidingWindow(board.slidingWindow),
          chartCount: clampLaneCount(board.chartCount),
          columnWidths: normalizeColumnWidths(board.columnWidths),
          items: normalizeBoardItems(board.items),
        }];
      });
      indicatorState.nextBoardId = Math.max(0, ...indicatorState.boards.map((board) => board.id)) + 1;
    } catch (error) {
      showIndicatorFormError(`无法读取已保存的 board：${error.message}`);
    }
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

  function clampLaneCount(value) {
    const count = Number(value);
    return Number.isInteger(count) ? Math.min(MAX_CHARTS, Math.max(1, count)) : 1;
  }

  function normalizeSlidingWindow(value) {
    return SLIDING_WINDOWS.some((entry) => entry.id === value) ? value : "1Y";
  }

  function normalizeColumnWidths(raw) {
    const widths = {};
    if (!raw || typeof raw !== "object") return widths;
    for (const [key, value] of Object.entries(raw)) {
      const width = Number(value);
      if (Number.isFinite(width) && width >= MIN_COLUMN_WIDTH) widths[key] = Math.round(width);
    }
    return widths;
  }

  function persistBoards() {
    try {
      localStorage.setItem(BOARD_STORAGE_KEY, JSON.stringify({ version: 1, boards: indicatorState.boards }));
    } catch (error) {
      showIndicatorFormError(`浏览器无法保存 board：${error.message}`);
    }
  }

  function bindBoardControls() {
    $("saveBoardAsButton").addEventListener("click", saveBoardAs);
    $("updateBoardButton").addEventListener("click", updateActiveBoard);
    $("deleteBoardButton").addEventListener("click", deleteActiveBoard);
    $("loadBoardButton").addEventListener("click", () => openBoard($("boardSelect").value));
    $("boardSelect").addEventListener("change", () => {
      const board = boardById($("boardSelect").value);
      $("boardName").value = board ? board.name : "";
      indicatorState.pendingBoardLoad = null;
      hideBoardStatus();
      renderBoardActions();
    });
  }

  function boardById(id) {
    return indicatorState.boards.find((board) => String(board.id) === String(id)) || null;
  }

  // Compares the working set against the board it came from. Keys are sorted so a config
  // rebuilt in a different property order does not read as a change, and a sliding board's
  // dates are excluded because they are derived from today rather than chosen.
  function boardSignature(snapshot) {
    const sliding = snapshot.dateMode === "sliding";
    return stableStringify({
      dateMode: snapshot.dateMode,
      slidingWindow: sliding ? snapshot.slidingWindow : null,
      startDate: sliding ? null : snapshot.startDate,
      endDate: sliding ? null : snapshot.endDate,
      chartCount: snapshot.chartCount,
      columnWidths: snapshot.columnWidths || {},
      items: (snapshot.items || []).map((item) => ({
        id: item.id, type: item.type, active: item.active, config: item.config,
      })),
    });
  }

  function stableStringify(value) {
    if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
    if (value && typeof value === "object") {
      return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
    }
    return JSON.stringify(value);
  }

  function boardIsDirty() {
    const board = boardById(indicatorState.activeBoardId);
    if (!board) return false;
    return boardSignature(currentBoardSnapshot(board.name)) !== boardSignature(board);
  }

  // Loading a board discards whatever is on screen, so warn when that would lose work:
  // either an edited board, or a working set that was never saved as one.
  function openingBoardWouldDiscardWork() {
    return boardIsDirty()
      || (indicatorState.activeBoardId === null && indicatorState.items.length > 0);
  }

  function renderBoardState() {
    if (!$("boardDirtyMark")) return;
    const board = boardById(indicatorState.activeBoardId);
    const dirty = boardIsDirty();
    $("boardDirtyMark").classList.toggle("is-hidden", !dirty);
    $("boardUnsavedNote").classList.toggle("is-hidden", !dirty);
    $("updateBoardButton").classList.toggle("is-emphasised", dirty);
    $("boardMenuSummary").title = board
      ? `当前 board：${board.name}${dirty ? " · 有未保存的修改" : ""}`
      : "尚未保存为 board";
    $("activeBoardLabel").textContent = board
      ? `当前 board：${board.name}（保存于 ${board.savedAt.slice(0, 10) || "—"}）${dirty ? " · 有未保存的修改" : ""}`
      : "当前工作区尚未保存为 board。";
  }

  function currentBoardSnapshot(name) {
    return {
      name,
      savedAt: new Date().toISOString(),
      startDate: $("startDate").value,
      endDate: $("endDate").value,
      dateMode: indicatorState.dateMode,
      slidingWindow: indicatorState.slidingWindow,
      chartCount: indicatorState.chartCount,
      columnWidths: { ...indicatorState.columnWidths },
      items: indicatorState.items.map((item) => structuredClone(serializeItem(item))),
    };
  }

  // Board feedback stays inside the board menu so it is visible where the click happened.
  function showBoardStatus(message) {
    $("boardStatus").textContent = message;
    $("boardStatus").classList.remove("is-hidden");
  }

  function hideBoardStatus() {
    $("boardStatus").classList.add("is-hidden");
    $("boardStatus").textContent = "";
  }

  function saveBoardAs() {
    hideBoardStatus();
    const name = $("boardName").value.trim();
    if (!name) return showBoardStatus("请先给这个 board 起一个名字。");
    if (!indicatorState.items.length) return showBoardStatus("当前没有 indicator，board 会是空的。");
    const board = { id: indicatorState.nextBoardId++, ...currentBoardSnapshot(name) };
    indicatorState.boards.push(board);
    indicatorState.activeBoardId = board.id;
    persistBoards();
    persistWorkspace();
    renderBoards();
  }

  function updateActiveBoard() {
    hideBoardStatus();
    const board = boardById(indicatorState.activeBoardId);
    if (!board) return showBoardStatus("当前没有打开的 board；请先用「另存为」创建一个。");
    Object.assign(board, currentBoardSnapshot($("boardName").value.trim() || board.name));
    persistBoards();
    renderBoards();
    showBoardStatus(`已更新「${board.name}」。`);
  }

  function deleteActiveBoard() {
    hideBoardStatus();
    const board = boardById($("boardSelect").value);
    if (!board) return showBoardStatus("请先在下拉框中选择要删除的 board。");
    indicatorState.boards = indicatorState.boards.filter((candidate) => candidate.id !== board.id);
    if (indicatorState.activeBoardId === board.id) indicatorState.activeBoardId = null;
    persistBoards();
    persistWorkspace();
    renderBoards();
  }

  // Opening a board restores the configuration and then re-requests every active
  // indicator, so a board always shows current data rather than a frozen snapshot.
  function openBoard(id) {
    hideBoardStatus();
    hideIndicatorFormError();
    const board = boardById(id);
    if (!board) return showBoardStatus("请先在下拉框中选择一个 board。");
    // Require a second click when loading would throw away unsaved work.
    if (openingBoardWouldDiscardWork() && String(indicatorState.pendingBoardLoad) !== String(board.id)) {
      indicatorState.pendingBoardLoad = board.id;
      const active = boardById(indicatorState.activeBoardId);
      return showBoardStatus(active
        ? `「${active.name}」有未保存的修改，载入会丢弃它们。先点「更新当前 board」保存，或再点一次「载入」确认。`
        : "当前工作区还没有保存为 board，载入会覆盖它。先点「另存为新 board」保存，或再点一次「载入」确认。");
    }
    indicatorState.pendingBoardLoad = null;
    indicatorState.dateMode = board.dateMode;
    indicatorState.slidingWindow = board.slidingWindow;
    if (board.startDate) $("startDate").value = board.startDate;
    if (board.endDate) $("endDate").value = board.endDate;
    // A board saved with a sliding range re-derives its dates from today, not from the
    // dates that happened to be on screen when it was saved.
    syncSlidingRange();
    renderDateMode();
    indicatorState.items = board.items.map((item) => ({
      id: item.id,
      type: item.type,
      config: structuredClone(item.config),
      active: item.active,
      status: item.type === "derived" ? "ready" : "stale",
      response: null,
      request: null,
      error: null,
    }));
    const largestLane = Math.max(1, ...indicatorState.items.map((item) => Number(item.config.chartLane) || 1));
    indicatorState.chartCount = Math.min(MAX_CHARTS, Math.max(largestLane, board.chartCount));
    indicatorState.nextId = Math.max(0, ...indicatorState.items.map((item) => item.id)) + 1;
    indicatorState.activeBoardId = board.id;
    indicatorState.selectedDetailId = null;
    indicatorState.editingId = null;
    indicatorState.hoverDate = null;
    indicatorState.draft.chartLane = "1";
    indicatorState.columnWidths = { ...board.columnWidths };
    persistWorkspace();
    renderBoards();
    renderScopeFields();
    renderIndicatorConfig();
    renderBuilderMode();
    refreshWorkspacePanels();
    refreshActiveIndicators();
  }

  function renderBoards() {
    const select = $("boardSelect");
    if (!select) return;
    const options = indicatorState.boards
      .map((board) => `<option value="${board.id}">${escapeHtml(board.name)} · ${board.items.length} indicators</option>`)
      .join("");
    select.innerHTML = `<option value="">选择一个 board…</option>${options}`;
    if (indicatorState.activeBoardId !== null) select.value = String(indicatorState.activeBoardId);
    const active = boardById(indicatorState.activeBoardId);
    if (active && !$("boardName").value.trim()) $("boardName").value = active.name;
    $("boardCount").textContent = String(indicatorState.boards.length);
    renderBoardState();
    renderBoardActions();
  }

  function renderBoardActions() {
    $("updateBoardButton").disabled = boardById(indicatorState.activeBoardId) === null;
    $("deleteBoardButton").disabled = boardById($("boardSelect").value) === null;
    $("loadBoardButton").disabled = boardById($("boardSelect").value) === null;
  }

  function renderIndicatorConfig() {
    const draft = indicatorState.draft;
    const config = $("indicatorConfig");
    if (!config) return;
    let html = "";
    if (draft.type === "implied_vol") {
      html = `${requestSystemFields(draft)}${maturityModeField(draft)}${maturityValueField(draft)}${strikeFields(draft)}${listedDiscoveryPanel(draft)}`;
      $("indicatorBuilderNote").textContent = "IV 使用精确 maturity + strike 坐标。Vol convention 与 layout 都是数据源请求字段；缺失值不会换成邻近坐标。";
    } else if (draft.type === "realized_vol") {
      html = `${requestSystemFields(draft)}<div class="field-grid two config-grid">
        <label class="field"><span>Window · sessions</span><input data-draft="rvWindow" type="number" min="2" step="1" list="rvWindowOptions" value="${escapeHtml(draft.rvWindow)}" /></label>
        <label class="field"><span>Alignment</span><select data-draft="rvAlignment"><option value="trailing" ${draft.rvAlignment === "trailing" ? "selected" : ""}>Trailing</option><option value="forward" ${draft.rvAlignment === "forward" ? "selected" : ""}>Forward</option></select></label>
      </div>`;
      $("indicatorBuilderNote").textContent = "RV 接受任意 ≥2 的整数窗口，不取最近档位。Spot 来自数据源 IV 响应，因此独立 RV 会明确使用 3M K/F 100% 作为取数载体；该坐标不进入 RV 公式。";
    } else if (draft.type === "spot") {
      html = `${requestSystemFields(draft)}<div class="system-default-card"><strong>无需额外参数</strong><span>原始未复权 spot / price-return source</span></div>`;
      $("indicatorBuilderNote").textContent = "当前 Cortex 数据路径把 spot 放在 IV response 内；系统用 3M K/F 100% 请求承载 spot，并在指标卡中明示。不会把该参考 IV 当作用户选择的指标。";
    } else if (draft.type === "derived") {
      ensureDerivedDefaults(draft);
      html = derivedOperandFields(draft);
      $("indicatorBuilderNote").textContent = "运算在浏览器内按共同观察日逐日进行，不发送新的取数请求。任一操作数缺失该日期或该日期无有效值时，结果保持为空，不插值、不前向填充；除数为 0 同样保持为空。";
    } else {
      html = `${requestSystemFields(draft)}${maturityModeField(draft)}${maturityValueField(draft)}${listedDiscoveryPanel(draft)}`;
      $("indicatorBuilderNote").textContent = "Forward 按所选 maturity 读取数据源 forward curve；系统用 K/F 100% 作为响应载体。该 moneyness 不改变同一期限的 forward 值。";
    }
    config.innerHTML = html;
    bindDraftFields();
    bindIndicatorDiscovery();
  }

  function ensureDerivedDefaults(draft) {
    const ids = operandCandidates().map((item) => String(item.id));
    if (!ids.includes(draft.operandA)) draft.operandA = ids[0] || "";
    if (!ids.includes(draft.operandB)) draft.operandB = ids[1] || ids[0] || "";
    if (!Object.hasOwn(OPERATOR_SYMBOLS, draft.operator)) draft.operator = "subtract";
  }

  // While editing a derived indicator its own id — and anything that already reads it —
  // must stay out of the operand list, otherwise saving would build a reference cycle.
  function operandCandidates() {
    if (indicatorState.editingId === null) return indicatorState.items;
    const blocked = dependencyClosure(indicatorState.editingId);
    return indicatorState.items.filter((item) => !blocked.has(item.id));
  }

  function dependencyClosure(id) {
    const blocked = new Set([Number(id)]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const item of indicatorState.items) {
        if (item.type !== "derived" || blocked.has(item.id)) continue;
        const references = [item.config.operandA, item.config.operandB].map(Number);
        if (references.some((reference) => blocked.has(reference))) {
          blocked.add(item.id);
          grew = true;
        }
      }
    }
    return blocked;
  }

  function derivedOperandFields(draft) {
    const candidates = operandCandidates();
    if (!candidates.length) {
      return '<div class="system-default-card"><strong>还没有可用的操作数</strong><span>先添加至少一个已保存 indicator，再用它们组合出新指标。</span></div>';
    }
    const operandOptions = (selected) => candidates
      .map((item) => `<option value="${item.id}" ${String(item.id) === String(selected) ? "selected" : ""}>${escapeHtml(indicatorLabel(item))}</option>`).join("");
    const operatorOptions = Object.entries(OPERATOR_SYMBOLS)
      .map(([key, symbol]) => `<option value="${key}" ${draft.operator === key ? "selected" : ""}>${symbol}</option>`).join("");
    return `<div class="derived-operands">
      <label class="field"><span>Indicator A</span><select data-draft="operandA">${operandOptions(draft.operandA)}</select></label>
      <label class="field operator-field"><span>运算</span><select data-draft="operator">${operatorOptions}</select></label>
      <label class="field"><span>Indicator B</span><select data-draft="operandB">${operandOptions(draft.operandB)}</select></label>
    </div><p class="derived-preview">${escapeHtml(derivedPreviewLabel(draft))}</p>`;
  }

  function derivedPreviewLabel(draft) {
    const left = itemById(draft.operandA);
    const right = itemById(draft.operandB);
    if (!left || !right) return "请选择两个已保存的 indicator。";
    return `${indicatorLabel(left)}  ${OPERATOR_SYMBOLS[draft.operator]}  ${indicatorLabel(right)}`;
  }

  function itemById(id) {
    return indicatorState.items.find((item) => String(item.id) === String(id)) || null;
  }

  function requestSystemFields(draft) {
    return `<div class="field-grid two config-grid request-system-fields">
      <label class="field"><span>Vol convention</span><select data-draft="volatilityConvention"><option value="bsVol" ${draft.volatilityConvention === "bsVol" ? "selected" : ""}>bsVol</option><option value="bnppVol" ${draft.volatilityConvention === "bnppVol" ? "selected" : ""}>bnppVol</option></select><small>数据源字段；通常只有 bsVol 可用。</small></label>
      <label class="field"><span>Layout</span><select data-draft="layout"><option value="matrix" ${draft.layout === "matrix" ? "selected" : ""}>Matrix</option><option value="vector" ${draft.layout === "vector" ? "selected" : ""}>Vector</option></select><small>数据源返回结构；数值语义不变。</small></label>
    </div>`;
  }

  function maturityModeField(draft) {
    return `<label class="field field-wide config-first"><span>Maturity type</span><select data-draft="maturityMode">
      <option value="sliding" ${draft.maturityMode === "sliding" ? "selected" : ""}>Sliding tenor</option>
      <option value="fixed" ${draft.maturityMode === "fixed" ? "selected" : ""}>Fixed date · theoretical allowed</option>
      <option value="listed" ${draft.maturityMode === "listed" ? "selected" : ""}>Listed expiry only</option>
    </select></label>`;
  }

  function maturityValueField(draft) {
    if (draft.maturityMode === "sliding") {
      const maturities = draft.strikeKind === "delta"
        ? state.capabilities?.deltaMaturities || []
        : state.capabilities?.slidingMaturities || [];
      return `<label class="field field-wide"><span>Sliding maturity</span><input data-draft="slidingMaturity" value="${escapeHtml(draft.slidingMaturity)}" list="indicatorMaturityOptions" autocomplete="off" /><datalist id="indicatorMaturityOptions">${optionList(maturities)}</datalist><small>可键盘输入，但必须是数据源 OpenAPI 列出的 tenor；不支持的值会在本地明确拒绝。</small></label>`;
    }
    const typeLabel = draft.maturityMode === "listed" ? "Listed expiry" : "Fixed maturity date";
    return `<label class="field field-wide"><span>${typeLabel}</span><input data-draft="expiry" type="date" value="${escapeHtml(draft.expiry)}" /><small>允许手输任意合法日期；精确点不存在时保持缺失，不改成最近日期。</small></label>`;
  }

  function strikeFields(draft) {
    const fixedMaturity = draft.maturityMode !== "sliding";
    const selectedKind = fixedMaturity && draft.strikeKind === "delta"
      ? "percentage"
      : !fixedMaturity && draft.strikeKind === "absolute"
        ? "percentage"
        : draft.strikeKind;
    draft.strikeKind = selectedKind;
    let coordinate = "";
    if (selectedKind === "percentage") {
      coordinate = `<div class="field-grid two config-grid">
        <label class="field"><span>Percentage</span><input data-draft="moneyness" type="number" step="0.1" value="${escapeHtml(draft.moneyness)}" list="indicatorMoneynessOptions" /><datalist id="indicatorMoneynessOptions">${optionList(state.capabilities?.moneynessLevels || [])}</datalist></label>
        <label class="field"><span>Relative to</span><select data-draft="moneynessBasis"><option value="relative_to_forward" ${draft.moneynessBasis === "relative_to_forward" ? "selected" : ""}>Forward · K/F</option><option value="relative_to_spot_ref" ${draft.moneynessBasis === "relative_to_spot_ref" ? "selected" : ""}>Spot reference · K/S</option></select></label>
      </div>`;
    } else if (selectedKind === "delta") {
      coordinate = `<label class="field field-wide"><span>Put / Call delta</span><input data-draft="delta" value="${escapeHtml(draft.delta)}" list="indicatorDeltaOptions" autocomplete="off" /><datalist id="indicatorDeltaOptions">${optionList(state.capabilities?.deltaStrikes || [])}</datalist><small>Delta 只支持 sliding maturity 和数据源官方 delta codes。</small></label>`;
    } else {
      coordinate = `<label class="field field-wide"><span>Absolute strike</span><input data-draft="absoluteStrike" type="number" min="0.000001" step="any" value="${escapeHtml(draft.absoluteStrike)}" /><small>允许任意正数；不存在的精确 strike 返回缺失，不自动取 listed 邻近值。</small></label>`;
    }
    const combinationNote = fixedMaturity ? "" : "<small>数据源 API 不支持 Sliding maturity + Absolute strike；系统不会自动把 3M 转成邻近 expiry。</small>";
    return `<label class="field field-wide"><span>Strike type</span><select data-draft="strikeKind">
      <option value="percentage" ${selectedKind === "percentage" ? "selected" : ""}>Percentage moneyness</option>
      <option value="delta" ${selectedKind === "delta" ? "selected" : ""} ${fixedMaturity ? "disabled" : ""}>Put / Call delta</option>
      <option value="absolute" ${selectedKind === "absolute" ? "selected" : ""} ${fixedMaturity ? "" : "disabled"}>Absolute strike</option>
    </select>${combinationNote}</label>${coordinate}`;
  }

  function optionList(values) {
    return values.map((value) => `<option value="${escapeHtml(value)}"></option>`).join("");
  }

  function bindDraftFields() {
    document.querySelectorAll("#indicatorConfig [data-draft]").forEach((field) => {
      const update = () => {
        indicatorState.draft[field.dataset.draft] = field.value;
        if (["maturityMode", "strikeKind"].includes(field.dataset.draft)) {
          indicatorState.discovery = null;
          renderIndicatorConfig();
        }
        if (["operandA", "operator", "operandB"].includes(field.dataset.draft)) {
          const preview = document.querySelector(".derived-preview");
          if (preview) preview.textContent = derivedPreviewLabel(indicatorState.draft);
        }
      };
      field.addEventListener("change", update);
      if (field.tagName === "INPUT") field.addEventListener("input", update);
    });
  }

  function listedDiscoveryPanel(draft) {
    if (draft.maturityMode !== "listed") return "";
    const discovery = indicatorState.discovery;
    const observationDate = discovery?.date || $("endDate").value || isoDate(new Date());
    let result = "";
    if (discovery?.status === "loading") {
      result = '<p class="coordinate-discovery-status">正在向数据源请求该观察日的 listed surface…</p>';
    } else if (discovery?.status === "error") {
      result = `<p class="coordinate-discovery-error">${escapeHtml(discovery.message)}</p>`;
    } else if (discovery?.status === "ready") {
      const expiries = discovery.snapshot.maturities.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
      const needsStrike = draft.type === "implied_vol" && draft.strikeKind === "absolute";
      result = `<div class="coordinate-grid discovery-selectors">
        <label class="field"><span>Available expiry</span><select id="indicatorAvailableExpiry"><option value="">请选择实际 expiry</option>${expiries}</select></label>
        ${needsStrike ? '<label class="field"><span>Available strike</span><select id="indicatorAvailableStrike" disabled><option value="">先选择 expiry</option></select></label>' : ""}
      </div><p id="indicatorCoordinateStatus" class="coordinate-discovery-status">数据源返回 ${discovery.snapshot.maturities.length} 个 expiry；系统没有自动选择。</p>
      <button id="applyIndicatorCoordinate" class="secondary-button discovery-apply" type="button" disabled>应用所选 listed 坐标</button>`;
    }
    return `<section class="coordinate-discovery" aria-label="listed 坐标发现">
      <div class="coordinate-discovery-heading"><strong>加载实际 listed 坐标</strong><small>手输仍然允许；加载结果只供明确选择，不替代当前输入。</small></div>
      <div class="field-grid discovery-loader"><label class="field"><span>Observation date</span><input id="indicatorObservationDate" type="date" value="${escapeHtml(observationDate)}" /></label><button id="loadIndicatorCoordinates" class="secondary-button" type="button" ${discovery?.status === "loading" ? "disabled" : ""}>加载可用坐标</button></div>${result}
    </section>`;
  }

  function bindIndicatorDiscovery() {
    $("loadIndicatorCoordinates")?.addEventListener("click", loadIndicatorCoordinates);
    $("indicatorAvailableExpiry")?.addEventListener("change", updateIndicatorDiscoverySelection);
    $("indicatorAvailableStrike")?.addEventListener("change", updateIndicatorApplyState);
    $("applyIndicatorCoordinate")?.addEventListener("click", applyIndicatorCoordinate);
  }

  async function loadIndicatorCoordinates() {
    const code = indicatorState.draft.instrumentCode.trim();
    const date = $("indicatorObservationDate").value;
    if (!code || !date) return showIndicatorFormError("加载坐标前需要 instrument code 和 observation date。");
    indicatorState.discovery = { status: "loading", code, date };
    renderIndicatorConfig();
    try {
      const response = await apiFetch(state.capabilities.endpoints.surface, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ volatilityRequest: {
          code,
          code_type: "bnpp",
          volatility_convention: indicatorState.draft.volatilityConvention,
          start_date: date,
          end_date: date,
          maturity_rule: "fixed",
          strike_rule: "fixed",
          layout: indicatorState.draft.layout,
        }}),
      });
      const payload = await response.json();
      const snapshot = payload.snapshots.find((item) => item.date === date);
      if (!snapshot) throw new Error("数据源在该观察日没有返回 listed surface。");
      indicatorState.discovery = { status: "ready", code, date, snapshot };
    } catch (error) {
      indicatorState.discovery = { status: "error", code, date, message: error.payload?.message || error.message };
    }
    renderIndicatorConfig();
  }

  function updateIndicatorDiscoverySelection() {
    const expiry = $("indicatorAvailableExpiry").value;
    const strike = $("indicatorAvailableStrike");
    const apply = $("applyIndicatorCoordinate");
    if (!strike) {
      apply.disabled = !expiry;
      $("indicatorCoordinateStatus").textContent = expiry
        ? `已选择实际 listed expiry ${expiry}；点击应用才会写入指标。`
        : "系统没有自动选择 expiry。";
      return;
    }
    apply.disabled = true;
    if (!expiry) {
      strike.disabled = true;
      strike.innerHTML = '<option value="">先选择 expiry</option>';
      return;
    }
    const points = indicatorState.discovery.snapshot.points.filter((point) => point.maturity === expiry);
    const valid = [...new Map(points.filter((point) => point.impliedVol !== null).map((point) => [point.strike, point])).values()];
    const invalid = points.filter((point) => point.impliedVol === null);
    strike.innerHTML = `<option value="">请选择有效 strike</option>${valid.map((point) => `<option value="${escapeHtml(point.strike)}">${escapeHtml(point.strike)} · IV ${formatPercent(point.impliedVol)}</option>`).join("")}`;
    strike.disabled = valid.length === 0;
    $("indicatorCoordinateStatus").textContent = `${expiry}：${valid.length} 个有效 strike，${invalid.length} 个无效点保留质量状态；未自动选择。`;
  }

  function updateIndicatorApplyState() {
    $("applyIndicatorCoordinate").disabled = !$("indicatorAvailableExpiry").value || !$("indicatorAvailableStrike").value;
  }

  function applyIndicatorCoordinate() {
    const expiry = $("indicatorAvailableExpiry").value;
    const strike = $("indicatorAvailableStrike")?.value;
    if (!expiry || ($("indicatorAvailableStrike") && !strike)) return;
    indicatorState.draft.expiry = expiry;
    if (strike) indicatorState.draft.absoluteStrike = strike;
    indicatorState.discovery = null;
    renderIndicatorConfig();
  }

  // One button drives both paths: it adds a new indicator, or writes the edited
  // configuration back onto the indicator being edited.
  function submitIndicator() {
    hideIndicatorFormError();
    try {
      validateScope(indicatorState.draft);
      validateDraft(indicatorState.draft);
    } catch (error) {
      showIndicatorFormError(error.message);
      return;
    }
    if (indicatorState.editingId !== null) {
      applyIndicatorEdit();
      return;
    }
    const item = {
      id: indicatorState.nextId++,
      type: indicatorState.draft.type,
      config: structuredClone(indicatorState.draft),
      active: true,
      status: initialStatus(indicatorState.draft.type),
      response: null,
      request: null,
      error: null,
    };
    indicatorState.items.push(item);
    persistWorkspace();
    if (item.type === "derived") {
      refreshWorkspacePanels();
      return;
    }
    indicatorState.selectedDetailId = item.id;
    renderSavedIndicators();
    fetchIndicator(item);
  }

  function applyIndicatorEdit() {
    const item = itemById(indicatorState.editingId);
    if (!item) {
      indicatorState.editingId = null;
      renderBuilderMode();
      return;
    }
    item.type = indicatorState.draft.type;
    item.config = structuredClone(indicatorState.draft);
    item.status = initialStatus(item.type);
    item.response = null;
    item.request = null;
    item.error = null;
    indicatorState.editingId = null;
    persistWorkspace();
    renderBuilderMode();
    if (item.type === "derived") {
      refreshWorkspacePanels();
      return;
    }
    fetchIndicator(item);
  }

  function startEditing(id) {
    const item = itemById(id);
    if (!item) return;
    hideIndicatorFormError();
    indicatorState.editingId = item.id;
    indicatorState.draft = structuredClone(item.config);
    indicatorState.draft.type = item.type;
    indicatorState.discovery = null;
    $("indicatorType").value = item.type;
    if (item.type !== "derived") $("instrumentCode").value = item.config.instrumentCode;
    renderScopeFields();
    renderIndicatorConfig();
    renderBuilderMode();
    renderSavedIndicators();
    $("indicatorBuilder").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function cancelEditing() {
    indicatorState.editingId = null;
    hideIndicatorFormError();
    const draft = defaultDraft($("indicatorType").value);
    draft.instrumentCode = $("instrumentCode").value.trim();
    indicatorState.draft = draft;
    indicatorState.discovery = null;
    renderScopeFields();
    renderIndicatorConfig();
    renderBuilderMode();
    renderSavedIndicators();
  }

  function duplicateIndicator(id) {
    const source = itemById(id);
    if (!source) return;
    hideIndicatorFormError();
    const copy = {
      id: indicatorState.nextId++,
      type: source.type,
      config: structuredClone(source.config),
      active: source.active,
      status: initialStatus(source.type),
      response: null,
      request: null,
      error: null,
    };
    indicatorState.items.splice(indicatorState.items.indexOf(source) + 1, 0, copy);
    persistWorkspace();
    refreshWorkspacePanels({ details: false });
    if (copy.type !== "derived" && copy.active) fetchIndicator(copy);
  }

  function renderBuilderMode() {
    const item = indicatorState.editingId === null ? null : itemById(indicatorState.editingId);
    if (indicatorState.editingId !== null && !item) indicatorState.editingId = null;
    const editing = item !== null;
    $("addIndicatorButton").querySelector("span").textContent = editing ? "保存修改" : "添加并加载指标";
    $("addIndicatorButton").querySelector("strong").textContent = editing ? "✓" : "＋";
    $("cancelEditButton").classList.toggle("is-hidden", !editing);
    $("builderModeNote").classList.toggle("is-hidden", !editing);
    $("builderModeNote").textContent = editing ? `正在编辑：${indicatorLabel(item)}` : "";
  }

  function initialStatus(type) {
    return type === "derived" ? "ready" : "queued";
  }

  function validateScope(config) {
    if (!state.capabilities) throw new Error("Capability registry 尚未载入，请稍后重试。");
    if (config?.type !== "derived" && !config?.instrumentCode?.trim()) {
      throw new Error("请输入该 indicator 的 instrument code。");
    }
    if (!$("startDate").value || !$("endDate").value) throw new Error("请选择完整日期范围。");
    if ($("startDate").value > $("endDate").value) throw new Error("开始日期不能晚于结束日期。");
  }

  function validateDraft(draft) {
    if (draft.type === "derived") {
      const left = itemById(draft.operandA);
      const right = itemById(draft.operandB);
      if (!left || !right) throw new Error("请选择两个已保存的 indicator 作为操作数。");
      if (!Object.hasOwn(OPERATOR_SYMBOLS, draft.operator)) throw new Error("请选择合法的运算符。");
      if (indicatorState.editingId !== null) {
        const blocked = dependencyClosure(indicatorState.editingId);
        if (blocked.has(left.id) || blocked.has(right.id)) {
          throw new Error("运算指标不能引用自己，也不能引用依赖它的指标。");
        }
      }
      return;
    }
    if (["implied_vol", "forward"].includes(draft.type)) {
      if (draft.maturityMode === "sliding") {
        const supported = draft.strikeKind === "delta"
          ? state.capabilities.deltaMaturities
          : state.capabilities.slidingMaturities;
        if (!supported.includes(draft.slidingMaturity)) {
          throw new Error(`数据源 OpenAPI 不接受 sliding maturity ${draft.slidingMaturity || "(空)"}；请输入官方 tenor。`);
        }
      } else if (!validIsoDate(draft.expiry)) {
        throw new Error("请输入合法的 fixed/listed expiry 日期。");
      }
    }
    if (draft.type === "implied_vol") {
      if (draft.strikeKind === "percentage") {
        const value = Number(draft.moneyness);
        if (!state.capabilities.moneynessLevels.some((level) => Number(level) === value)) {
          throw new Error(`数据源 OpenAPI 不接受 moneyness ${draft.moneyness || "(空)"}；请输入官方离散档位。`);
        }
      } else if (draft.strikeKind === "delta") {
        if (draft.maturityMode !== "sliding" || !state.capabilities.deltaStrikes.includes(draft.delta)) {
          throw new Error("Delta 只接受 sliding maturity 与数据源官方 delta code。");
        }
      } else if (!(Number(draft.absoluteStrike) > 0)) {
        throw new Error("Absolute strike 必须是正数。");
      }
    }
    if (draft.type === "realized_vol") {
      const window = Number(draft.rvWindow);
      const minimum = state.capabilities.rvWindowRange.minimum;
      if (!Number.isInteger(window) || window < minimum) {
        throw new Error(`RV window 必须是 ≥ ${minimum} 的整数；不会自动取最近档位。`);
      }
    }
  }

  function validIsoDate(value) {
    return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`));
  }

  function buildIndicatorRequest(item) {
    const base = {
      code: item.config.instrumentCode.trim(),
      code_type: "bnpp",
      volatility_convention: item.config.volatilityConvention,
      start_date: $("startDate").value,
      end_date: $("endDate").value,
      layout: item.config.layout,
    };
    let volatilityRequest;
    if (item.type === "implied_vol") {
      volatilityRequest = coordinateRequest(base, item.config, true);
    } else if (item.type === "forward") {
      volatilityRequest = coordinateRequest(base, { ...item.config, strikeKind: "percentage", moneynessBasis: "relative_to_forward", moneyness: "100" }, false);
    } else {
      volatilityRequest = coordinateRequest(base, defaultDraft("implied_vol"), false);
    }
    return {
      volatilityRequest,
      rvWindowSessions: item.type === "realized_vol" ? Number(item.config.rvWindow) : 2,
      rvAlignment: item.type === "realized_vol" ? item.config.rvAlignment : "trailing",
    };
  }

  function coordinateRequest(base, config, includeStrikeChoice) {
    if (config.maturityMode === "sliding") {
      if (includeStrikeChoice && config.strikeKind === "delta") {
        return { ...base, maturity_rule: "sliding", strike_rule: "delta", low_delta_strike: config.delta, high_delta_strike: config.delta, low_maturity: config.slidingMaturity, high_maturity: config.slidingMaturity };
      }
      const strike = includeStrikeChoice ? Number(config.moneyness) : 100;
      return { ...base, maturity_rule: "sliding", strike_rule: includeStrikeChoice ? config.moneynessBasis : "relative_to_forward", low_strike: strike, high_strike: strike, low_maturity: config.slidingMaturity, high_maturity: config.slidingMaturity };
    }
    if (includeStrikeChoice && config.strikeKind === "absolute") {
      const strike = Number(config.absoluteStrike);
      return { ...base, maturity_rule: config.maturityMode, strike_rule: "fixed", low_fixed_strike: strike, high_fixed_strike: strike, low_fixed_maturity: config.expiry, high_fixed_maturity: config.expiry };
    }
    const strike = includeStrikeChoice ? Number(config.moneyness) : 100;
    return { ...base, maturity_rule: config.maturityMode, strike_rule: includeStrikeChoice ? config.moneynessBasis : "relative_to_forward", low_strike: strike, high_strike: strike, low_fixed_maturity: config.expiry, high_fixed_maturity: config.expiry };
  }

  async function fetchIndicator(item) {
    if (!item.active || !indicatorState.items.some((candidate) => candidate.id === item.id)) return;
    if (item.type === "derived") {
      refreshWorkspacePanels();
      return;
    }
    item.status = "loading";
    item.error = null;
    refreshWorkspacePanels();
    const started = performance.now();
    try {
      validateScope(item.config);
      item.request = buildIndicatorRequest(item);
      const response = await apiFetch(state.capabilities.endpoints.compare, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(item.request),
      });
      const payload = await response.json();
      if (!indicatorState.items.some((candidate) => candidate.id === item.id)) return;
      payload.activity.push({
        code: "BROWSER_RENDER_READY",
        stage: "frontend",
        message: `浏览器已收到该 indicator 的完整响应，用时 ${Math.round(performance.now() - started)} ms。`,
        affectedObservations: 0,
        suggestedAction: null,
      });
      item.response = payload;
      item.status = "ready";
    } catch (error) {
      item.status = "error";
      item.error = error.payload?.message || error.message || "指标加载失败";
      item.response = null;
    }
    refreshWorkspacePanels();
  }

  async function refreshActiveIndicators() {
    hideIndicatorFormError();
    // Catch the day rolling over on a tab that has been open since yesterday.
    if (syncSlidingRange()) {
      renderDateMode();
      persistWorkspace();
    }
    const fetchable = indicatorState.items.filter((item) => item.active && item.type !== "derived");
    await Promise.all(fetchable.map(fetchIndicator));
    refreshWorkspacePanels();
  }

  function invalidateIndicators() {
    indicatorState.discovery = null;
    for (const item of indicatorState.items) {
      if (item.type === "derived") continue;
      item.status = "stale";
      item.response = null;
      item.error = null;
    }
    persistWorkspace();
    refreshWorkspacePanels();
  }

  // Every view reads from one recomputed series index so derived indicators, the chart
  // stack, the cross-chart readout and the statistics table can never drift apart.
  function refreshWorkspacePanels({ details = true } = {}) {
    refreshSeriesIndex();
    renderSavedIndicators();
    renderIndicatorChart();
    renderIndicatorStats();
    renderCrosshairReadout(indicatorState.hoverDate);
    if (details) renderIndicatorDetails();
  }

  function refreshSeriesIndex() {
    const index = new Map();
    for (const item of indicatorState.items) resolveSeries(item, index, new Set());
    indicatorState.seriesIndex = index;
  }

  function resolveSeries(item, index, stack) {
    if (index.has(item.id)) return index.get(item.id);
    let entry;
    if (item.type === "derived") {
      entry = computeDerivedSeries(item, index, stack);
      item.status = entry.error ? "error" : "ready";
      item.error = entry.error;
    } else if (item.status === "ready" && item.response) {
      const key = indicatorValueKey(item.type);
      entry = { points: item.response.series.map((point) => ({ date: point.date, value: numericValue(point[key]) })), error: null };
    } else {
      entry = { points: null, error: item.error || indicatorStatus(item) };
    }
    entry.byDate = entry.points ? new Map(entry.points.map((point) => [point.date, point.value])) : new Map();
    index.set(item.id, entry);
    return entry;
  }

  function computeDerivedSeries(item, index, stack) {
    if (stack.has(item.id)) return { points: null, error: "指标运算的引用形成了循环。" };
    const config = item.config;
    const left = itemById(config.operandA);
    const right = itemById(config.operandB);
    if (!left || !right) return { points: null, error: "引用的 indicator 已不存在，无法计算。" };
    if (!Object.hasOwn(OPERATOR_SYMBOLS, config.operator)) return { points: null, error: "运算符不合法。" };
    const nested = new Set(stack).add(item.id);
    const leftEntry = resolveSeries(left, index, nested);
    const rightEntry = resolveSeries(right, index, nested);
    if (!leftEntry.points) return { points: null, error: `操作数「${indicatorLabel(left)}」不可用：${leftEntry.error}` };
    if (!rightEntry.points) return { points: null, error: `操作数「${indicatorLabel(right)}」不可用：${rightEntry.error}` };
    const points = leftEntry.points
      .filter((point) => rightEntry.byDate.has(point.date))
      .map((point) => ({ date: point.date, value: applyOperator(config.operator, point.value, rightEntry.byDate.get(point.date)) }));
    if (!points.length) return { points: null, error: "两个操作数在当前日期范围内没有共同观察日。" };
    return { points, error: null };
  }

  function applyOperator(operator, left, right) {
    if (left === null || right === null) return null;
    if (operator === "add") return left + right;
    if (operator === "subtract") return left - right;
    if (operator === "multiply") return left * right;
    if (right === 0) return null;
    const value = left / right;
    return Number.isFinite(value) ? value : null;
  }

  function numericValue(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function indicatorUnit(item, depth = 0) {
    if (item.type !== "derived") {
      if (VOL_TYPES.has(item.type)) return "vol";
      return PRICE_TYPES.has(item.type) ? "price" : "mixed";
    }
    if (depth > MAX_CHARTS * 2) return "mixed";
    if (["multiply", "divide"].includes(item.config.operator)) return "ratio";
    const left = itemById(item.config.operandA);
    const right = itemById(item.config.operandB);
    if (!left || !right) return "mixed";
    const leftUnit = indicatorUnit(left, depth + 1);
    return leftUnit === indicatorUnit(right, depth + 1) ? leftUnit : "mixed";
  }

  function unitSuffix(item) {
    return indicatorUnit(item) === "vol" ? "%" : "";
  }

  function itemColor(item) {
    return PALETTE[(item.id - 1) % PALETTE.length];
  }

  function handleSavedIndicatorChange(event) {
    const laneSelect = event.target.closest("[data-indicator-lane]");
    if (laneSelect) {
      const item = indicatorState.items.find((candidate) => candidate.id === Number(laneSelect.dataset.indicatorLane));
      if (!item) return;
      item.config.chartLane = laneSelect.value;
      persistWorkspace();
      refreshWorkspacePanels({ details: false });
      return;
    }
    const toggle = event.target.closest("[data-indicator-toggle]");
    if (!toggle) return;
    const item = indicatorState.items.find((candidate) => candidate.id === Number(toggle.dataset.indicatorToggle));
    if (!item) return;
    item.active = toggle.checked;
    persistWorkspace();
    refreshWorkspacePanels({ details: false });
    if (item.active && item.type !== "derived" && !item.response) fetchIndicator(item);
  }

  function addChartLane() {
    if (indicatorState.chartCount >= MAX_CHARTS) return;
    indicatorState.chartCount += 1;
    indicatorState.draft.chartLane = String(indicatorState.chartCount);
    persistWorkspace();
    renderScopeFields();
    refreshWorkspacePanels({ details: false });
  }

  function handleChartStackClick(event) {
    const button = event.target.closest("[data-chart-remove]");
    if (!button) return;
    const lane = Number(button.dataset.chartRemove);
    if (!Number.isInteger(lane) || lane < 1 || lane > indicatorState.chartCount || indicatorState.chartCount <= 1) return;
    if (indicatorState.items.some((item) => Number(item.config.chartLane) === lane)) {
      showIndicatorFormError(`坐标 ${lane} 仍有 indicator；请先在保存卡片中移动或删除这些 indicator。`);
      return;
    }
    for (const item of indicatorState.items) {
      if (Number(item.config.chartLane) > lane) item.config.chartLane = String(Number(item.config.chartLane) - 1);
    }
    indicatorState.chartCount -= 1;
    const draftLane = Number(indicatorState.draft.chartLane);
    if (draftLane > lane) indicatorState.draft.chartLane = String(draftLane - 1);
    else if (draftLane === lane) indicatorState.draft.chartLane = String(Math.min(lane, indicatorState.chartCount));
    persistWorkspace();
    renderScopeFields();
    refreshWorkspacePanels({ details: false });
  }

  function handleSavedIndicatorClick(event) {
    const detailButton = event.target.closest("[data-indicator-detail]");
    if (detailButton) {
      indicatorState.selectedDetailId = Number(detailButton.dataset.indicatorDetail);
      persistWorkspace();
      renderIndicatorDetails();
      $("resultWorkspace").scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    const editButton = event.target.closest("[data-indicator-edit]");
    if (editButton) return startEditing(Number(editButton.dataset.indicatorEdit));
    const duplicateButton = event.target.closest("[data-indicator-duplicate]");
    if (duplicateButton) return duplicateIndicator(Number(duplicateButton.dataset.indicatorDuplicate));
    const deleteButton = event.target.closest("[data-indicator-delete]");
    if (!deleteButton) return;
    const deletedId = Number(deleteButton.dataset.indicatorDelete);
    const dependents = indicatorState.items.filter((item) => item.type === "derived"
      && [item.config.operandA, item.config.operandB].some((operand) => String(operand) === String(deletedId)));
    if (dependents.length) {
      showIndicatorFormError(`该 indicator 被 ${dependents.length} 个运算指标引用（${dependents.map(indicatorLabel).join("；")}），请先删除这些运算指标。`);
      return;
    }
    hideIndicatorFormError();
    indicatorState.items = indicatorState.items.filter((item) => item.id !== deletedId);
    if (indicatorState.selectedDetailId === deletedId) indicatorState.selectedDetailId = null;
    persistWorkspace();
    refreshWorkspacePanels();
  }

  function renderSavedIndicators() {
    $("indicatorCount").textContent = String(indicatorState.items.length);
    syncDerivedOperandOptions();
    if (!indicatorState.items.length) {
      $("savedIndicators").innerHTML = '<p class="empty-list-copy">尚未添加指标。</p>';
      return;
    }
    const laneOptions = (selected) => Array.from({ length: indicatorState.chartCount }, (_, index) => index + 1).map((lane) => `<option value="${lane}" ${String(lane) === String(selected) ? "selected" : ""}>坐标 ${lane}</option>`).join("");
    $("savedIndicators").innerHTML = indicatorState.items.map((item) => {
      const label = escapeHtml(indicatorLabel(item));
      return `<article class="saved-indicator ${item.active ? "is-active" : ""} ${item.id === indicatorState.editingId ? "is-editing" : ""}">
      <label class="indicator-toggle"><input type="checkbox" data-indicator-toggle="${item.id}" ${item.active ? "checked" : ""}/><span aria-hidden="true"></span></label>
      <div class="saved-indicator-copy"><strong>${label}</strong><small>${escapeHtml(indicatorDetail(item))}</small><em class="indicator-status status-${item.status}">${escapeHtml(indicatorStatus(item))}</em>${item.error ? `<p>${escapeHtml(item.error)}</p>` : ""}</div>
      <div class="saved-indicator-actions">
        <select class="indicator-lane-select" data-indicator-lane="${item.id}" aria-label="${label} 所属坐标">${laneOptions(item.config.chartLane)}</select>
        <div class="saved-indicator-buttons">
          <button class="card-action" type="button" data-indicator-edit="${item.id}" aria-label="编辑 ${label}">编辑</button>
          <button class="card-action" type="button" data-indicator-duplicate="${item.id}" aria-label="复制 ${label}">复制</button>
          <button class="card-action" type="button" data-indicator-detail="${item.id}" ${item.response ? "" : "disabled"} aria-label="查看 ${label} 详情">详情</button>
        </div>
        <button class="delete-indicator" type="button" data-indicator-delete="${item.id}" aria-label="删除 ${label}">×</button>
      </div>
    </article>`;
    }).join("");
  }

  // Keeps the derived operand dropdowns in step with the saved list without re-rendering
  // the whole config panel on every status change.
  function syncDerivedOperandOptions() {
    if (indicatorState.draft.type !== "derived") return;
    const signature = indicatorState.items.map((item) => `${item.id}:${indicatorLabel(item)}`).join("|");
    if (signature === indicatorState.operandSignature) return;
    indicatorState.operandSignature = signature;
    renderIndicatorConfig();
  }

  function indicatorLabel(item, depth = 0) {
    const config = item.config;
    if (item.type === "derived") {
      if (depth > MAX_CHARTS * 2) return "指标运算";
      const left = itemById(config.operandA);
      const right = itemById(config.operandB);
      const symbol = OPERATOR_SYMBOLS[config.operator] || "?";
      const leftLabel = left ? indicatorLabel(left, depth + 1) : "已删除";
      const rightLabel = right ? indicatorLabel(right, depth + 1) : "已删除";
      return `(${leftLabel}) ${symbol} (${rightLabel})`;
    }
    const prefix = `${config.instrumentCode} · `;
    if (item.type === "implied_vol") return `${prefix}IV · ${coordinateLabel(config)}`;
    if (item.type === "realized_vol") return `${prefix}RV · ${config.rvWindow} sessions · ${config.rvAlignment}`;
    if (item.type === "forward") return `${prefix}Forward · ${maturityLabel(config)}`;
    return `${prefix}Spot · 原始未复权`;
  }

  function coordinateLabel(config) {
    let strike;
    if (config.strikeKind === "percentage") strike = `${config.moneynessBasis === "relative_to_forward" ? "K/F" : "K/S"} ${config.moneyness}%`;
    else if (config.strikeKind === "delta") strike = `Delta ${config.delta}`;
    else strike = `Strike ${config.absoluteStrike}`;
    return `${maturityLabel(config)} · ${strike}`;
  }

  function maturityLabel(config) {
    return config.maturityMode === "sliding" ? config.slidingMaturity : `${config.maturityMode} ${config.expiry}`;
  }

  function indicatorDetail(item) {
    const wire = `${item.config.volatilityConvention} · ${item.config.layout}`;
    const placement = `坐标 ${item.config.chartLane}`;
    if (item.type === "derived") return `${placement} · 浏览器本地按共同观察日计算 · 不发送新的取数请求`;
    if (item.type === "realized_vol") return `${placement} · price-return RV · spot via reference 3M K/F 100% · ${wire} carrier`;
    if (item.type === "spot") return `${placement} · 数据源 spot · 未复权 · reference 3M K/F 100% · ${wire} carrier`;
    if (item.type === "forward") return `${placement} · 数据源 forward curve · K/F 100% response carrier · ${wire}`;
    return `${placement} · ${wire} · exact coordinate · no substitution`;
  }

  function indicatorStatus(item) {
    if (item.type === "derived" && item.status === "ready") return "已计算";
    return { queued: "等待加载", loading: "加载中", ready: "已加载", stale: "范围已变化，待刷新", error: "加载失败" }[item.status] || item.status;
  }

  function renderIndicatorChart() {
    if (!window.Plotly || !$("indicatorCharts")) return;
    renderChartShells();
    const active = indicatorState.items.filter((item) => item.active);
    const ready = active.filter((item) => indicatorState.seriesIndex.get(item.id)?.points);
    const start = $("startDate").value;
    const end = $("endDate").value;
    for (let lane = 1; lane <= indicatorState.chartCount; lane += 1) {
      const laneActive = active.filter((item) => Number(item.config.chartLane) === lane);
      const laneReady = ready.filter((item) => Number(item.config.chartLane) === lane);
      const traces = laneReady.map((item) => indicatorTrace(item));
      const annotations = traces.length ? [] : [{
        text: laneActive.some((item) => item.status === "loading") ? "正在加载此坐标的 indicator…" : "把 indicator 分配到此坐标",
        showarrow: false,
        xref: "paper",
        yref: "paper",
        x: 0.5,
        y: 0.5,
        font: { color: "#7b8780", size: 14 },
      }];
      const div = $(`indicatorChart-${lane}`);
      $(`chartPaneCount-${lane}`).textContent = `${laneActive.length} active · ${laneReady.length} loaded`;
      Promise.resolve(Plotly.react(div, traces, {
        margin: { l: 62, r: 68, t: 22, b: 48 },
        paper_bgcolor: "#fffef9",
        plot_bgcolor: "#fffef9",
        hovermode: "x unified",
        dragmode: "zoom",
        legend: { orientation: "h", y: 1.1, x: 0 },
        font: { family: "Inter, Microsoft YaHei, sans-serif", size: 10, color: "#536159" },
        // Snapping to data (not the cursor) keeps the guide line on the same observation
        // date in every lane, so the synchronized lines all sit on one vertical.
        xaxis: { title: "Observation date", type: "date", range: start && end ? [start, end] : undefined, gridcolor: "#e8ebe4", showspikes: true, spikemode: "across", spikesnap: "data", spikedash: "dot", spikecolor: "#6f7f76", spikethickness: 1 },
        yaxis: { title: "Volatility (%)", gridcolor: "#e8ebe4", zeroline: false },
        yaxis2: { title: "Price / ratio", overlaying: "y", side: "right", showgrid: false, zeroline: false },
        annotations,
        uirevision: `chart-${lane}-${start}-${end}`,
      }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d"] })).then(() => bindChartSync(div));
    }
    const instruments = new Set(indicatorState.items.filter((item) => item.type !== "derived").map((item) => item.config.instrumentCode));
    $("timeseriesStatus").textContent = `${indicatorState.chartCount}/${MAX_CHARTS} charts · ${active.length} active`;
    $("timeseriesTitle").textContent = indicatorState.items.length ? `${instruments.size} instruments · ${indicatorState.items.length} indicators` : "空白时序图";
    $("timeseriesSubtitle").textContent = `${start || "—"} → ${end || "—"} · hover 任一坐标会同时读出该日期在全部坐标上的数值，X 轴缩放同步。`;
    $("addChartButton").disabled = indicatorState.chartCount >= MAX_CHARTS;
    renderIndicatorWarnings(active);
  }

  function renderChartShells() {
    const container = $("indicatorCharts");
    if (Number(container.dataset.chartCount) === indicatorState.chartCount) return;
    chartDivs().forEach((div) => Plotly.purge(div));
    container.dataset.chartCount = String(indicatorState.chartCount);
    container.innerHTML = Array.from({ length: indicatorState.chartCount }, (_, index) => {
      const lane = index + 1;
      const removeButton = indicatorState.chartCount > 1
        ? `<button class="remove-chart-button" type="button" data-chart-remove="${lane}">删除坐标</button>` : "";
      return `<article class="panel chart-panel timeseries-panel" data-chart-lane="${lane}">
        <div class="panel-heading"><div><p class="eyebrow">CHART ${lane}</p><h3>坐标 ${lane}</h3></div><div class="chart-pane-actions"><span id="chartPaneCount-${lane}" class="chart-pane-count">0 active</span><span class="axis-note">左轴：波动率 % · 右轴：价格与比值 · 框选缩放</span>${removeButton}</div></div>
        <div id="indicatorChart-${lane}" class="chart timeseries-chart"></div>
      </article>`;
    }).join("");
  }

  function bindChartSync(div) {
    if (!div?.on || div.dataset.syncBound === "true") return;
    div.dataset.syncBound = "true";
    // Charts we drive programmatically echo these events straight back; ignoring the
    // echo here keeps the flag scoped to one synchronous fan-out instead of a timer,
    // which previously let a source unhover cancel the hover that followed it.
    div.on("plotly_hover", (event) => {
      if (indicatorState.hoverSyncing) return;
      const xValue = event.points?.[0]?.x;
      syncHover(div, xValue);
      renderCrosshairReadout(hoverDateKey(xValue));
    });
    div.on("plotly_unhover", () => {
      if (indicatorState.hoverSyncing) return;
      clearSynchronizedHover(div);
    });
    div.on("plotly_relayout", (event) => syncXZoom(div, event));
  }

  function hoverDateKey(xValue) {
    return xValue === undefined || xValue === null ? null : String(xValue).slice(0, 10);
  }

  // Hovering one lane has to answer "what did every other lane do on this same day",
  // so the readout lists every active indicator across all lanes for the hovered date.
  function renderCrosshairReadout(date) {
    const box = $("crosshairReadout");
    if (!box) return;
    indicatorState.hoverDate = date;
    const active = indicatorState.items.filter((item) => item.active);
    if (!date || !active.length) {
      box.classList.add("is-hidden");
      box.innerHTML = "";
      return;
    }
    const lanes = [];
    for (let lane = 1; lane <= indicatorState.chartCount; lane += 1) {
      const rows = active
        .filter((item) => Number(item.config.chartLane) === lane)
        .map((item) => {
          const entry = indicatorState.seriesIndex.get(item.id);
          const value = entry?.byDate?.get(date);
          const text = value === undefined || value === null ? "—" : `${formatNumber(value, 4)}${unitSuffix(item)}`;
          const missing = value === undefined || value === null ? " is-missing" : "";
          return `<li><i style="background:${itemColor(item)}"></i><span>${escapeHtml(indicatorLabel(item))}</span><strong class="readout-value${missing}">${escapeHtml(text)}</strong></li>`;
        });
      if (rows.length) lanes.push(`<div class="readout-lane"><small>坐标 ${lane}</small><ul>${rows.join("")}</ul></div>`);
    }
    if (!lanes.length) {
      box.classList.add("is-hidden");
      box.innerHTML = "";
      return;
    }
    box.classList.remove("is-hidden");
    box.innerHTML = `<div class="readout-date"><small>HOVER DATE</small><strong>${escapeHtml(date)}</strong></div><div class="readout-lanes">${lanes.join("")}</div>`;
  }

  function chartDivs() {
    return Array.from(document.querySelectorAll("#indicatorCharts .timeseries-chart"));
  }

  // Plotly only draws the vertical spike line for the {xval} form of Fx.hover, and only
  // when xval is the numeric axis coordinate — {curveNumber, pointNumber} references
  // produce the tooltip alone, which is why the guide line used to stay on one chart.
  function syncHover(source, xValue) {
    const xval = axisTimestamp(xValue);
    if (xval === null) return;
    indicatorState.hoverSyncing = true;
    try {
      for (const div of chartDivs()) {
        if (div === source || !Array.isArray(div.data) || !div.data.length) continue;
        Plotly.Fx.hover(div, { xval }, laneSubplot(div));
      }
    } finally {
      indicatorState.hoverSyncing = false;
    }
  }

  // A lane holding only right-axis series (prices, ratios) lives on subplot xy2, and
  // asking for xy there finds no points and draws no guide line.
  function laneSubplot(div) {
    return div.data.some((trace) => (trace.yaxis || "y") === "y") ? "xy" : "xy2";
  }

  function axisTimestamp(xValue) {
    if (xValue === undefined || xValue === null) return null;
    if (typeof xValue === "number") return xValue;
    const parsed = Date.parse(xValue instanceof Date ? xValue.toISOString() : String(xValue));
    return Number.isFinite(parsed) ? parsed : null;
  }

  function clearSynchronizedHover(source) {
    indicatorState.hoverSyncing = true;
    try {
      for (const div of chartDivs()) if (div !== source) Plotly.Fx.unhover(div);
    } finally {
      indicatorState.hoverSyncing = false;
    }
  }

  function syncXZoom(source, event) {
    if (indicatorState.zoomSyncing) return;
    const update = {};
    if (event["xaxis.range[0]"] !== undefined && event["xaxis.range[1]"] !== undefined) {
      update["xaxis.range[0]"] = event["xaxis.range[0]"];
      update["xaxis.range[1]"] = event["xaxis.range[1]"];
    } else if (event["xaxis.autorange"] === true) {
      update["xaxis.autorange"] = true;
    } else {
      return;
    }
    indicatorState.zoomSyncing = true;
    const updates = chartDivs().filter((div) => div !== source).map((div) => Plotly.relayout(div, update));
    Promise.all(updates).finally(() => { indicatorState.zoomSyncing = false; });
  }

  function renderIndicatorDetails() {
    if (document.querySelector('input[name="queryKind"]:checked')?.value !== "compare") return;
    const ready = indicatorState.items.filter((item) => item.response && item.status === "ready");
    if (!ready.length) {
      $("resultWorkspace").classList.add("is-hidden");
      $("detailIndicatorField").classList.add("is-hidden");
      return;
    }
    let item = ready.find((candidate) => candidate.id === indicatorState.selectedDetailId) || ready.at(-1);
    indicatorState.selectedDetailId = item.id;
    $("detailIndicatorSelect").innerHTML = ready.map((candidate) => `<option value="${candidate.id}" ${candidate.id === item.id ? "selected" : ""}>${escapeHtml(indicatorLabel(candidate))}</option>`).join("");
    $("detailIndicatorField").classList.remove("is-hidden");
    $("resultWorkspace").classList.remove("is-hidden");
    $("welcomeState").classList.add("is-hidden");
    $("loadingState").classList.add("is-hidden");
    $("errorPanel").classList.add("is-hidden");
    $("compareCharts").classList.add("is-hidden");
    $("surfaceCharts").classList.add("is-hidden");
    renderIndicatorDetailHeader(item);
    renderIndicatorDetailSummary(item);
    renderIndicatorDetailTable(item);
    renderIndicatorDetailMethodology(item);
    renderIndicatorDetailQuality(item);
    renderIndicatorDetailActivity(item);
    renderIndicatorDetailDisclosures(item);
    renderIndicatorDetailWarnings(item);
  }

  function renderIndicatorDetailHeader(item) {
    const request = item.request.volatilityRequest;
    $("resultEyebrow").textContent = "INDICATOR DETAIL";
    $("resultTitle").textContent = indicatorLabel(item);
    $("resultSubtitle").textContent = `坐标 ${item.config.chartLane} · ${request.start_date} → ${request.end_date} · 当前只展示所选 indicator 的数据与后台记录`;
    $("cacheBadge").textContent = item.response.source.cacheStatus.toUpperCase();
    $("requestIdBadge").textContent = `Request ${item.response.requestId}`;
  }

  function renderIndicatorDetailSummary(item) {
    const data = item.response;
    const key = indicatorValueKey(item.type);
    const latest = [...data.series].reverse().find((point) => point[key] !== null && point[key] !== undefined);
    const usable = data.series.filter((point) => point[key] !== null && point[key] !== undefined).length;
    const value = latest ? latest[key] : null;
    const suffix = ["implied_vol", "realized_vol"].includes(item.type) ? "%" : "";
    const cards = [
      ["Latest selected value", value === null ? "—" : `${formatNumber(value, 3)}${suffix}`, latest?.date || "无有效值"],
      ["Observations", formatNumber(data.series.length, 0), `${usable} usable selected values`],
      ["Usable IV", formatNumber(data.dataQuality.usableIvCount, 0), "response coordinate"],
      ["Invalid IV", formatNumber(data.dataQuality.invalidIvCount, 0), "raw retained · effective null"],
    ];
    $("summaryCards").innerHTML = cards.map(([label, valueText, note]) => `<article class="summary-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(valueText)}</strong><em>${escapeHtml(note)}</em></article>`).join("");
  }

  function renderIndicatorDetailTable(item) {
    const selectedKey = indicatorValueKey(item.type);
    const selectedLabel = TYPE_LABELS[item.type];
    const headers = ["Date", `Selected · ${selectedLabel}`, "Spot · unadjusted", "Forward", "Raw IV %", "Effective IV %", "RV %", "Quality flags"];
    $("resultTableHead").innerHTML = `<tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr>`;
    $("resultTableBody").innerHTML = item.response.series.map((point) => `<tr>
      <td>${escapeHtml(point.date)}</td><td>${tableValue(point[selectedKey])}</td><td>${tableValue(point.spot)}</td><td>${tableValue(point.forward)}</td>
      <td>${tableValue(point.rawImpliedVol)}</td><td>${tableValue(point.impliedVol)}</td><td>${tableValue(point.realizedVol)}</td><td>${flagHtml(point.qualityFlags)}</td>
    </tr>`).join("");
    $("tableTitle").textContent = `${selectedLabel} · 完整响应明细`;
    $("tableCount").textContent = `${item.response.series.length} rows`;
    $("tableFootnote").textContent = "Selected 列是图中该 indicator 使用的值；其余列保留后端同一响应中的载体、原值和质量信息。Raw IV 不会因无效而被删除。";
  }

  function renderIndicatorDetailMethodology(item) {
    const data = item.response;
    const method = data.methodology;
    const request = item.request.volatilityRequest;
    const carrier = item.type === "realized_vol" || item.type === "spot"
      ? "3M K/F 100% reference response carrier"
      : item.type === "forward" ? "selected maturity + K/F 100% response carrier" : "exact requested IV coordinate";
    $("methodologyContent").innerHTML = definitionGrid([
      ["Selected indicator", indicatorLabel(item)], ["Request coordinate", coordinateRequestLabel(request)],
      ["Vol convention", request.volatility_convention], ["Layout", request.layout], ["Data carrier", carrier],
      ["IV", method.ivLabel], ["RV", method.rvLabel], ["RV formula", method.rvFormula],
      ["Annualization", `${method.annualization} trading sessions`], ["Spot", method.spotNote],
      ["Corporate action adjustment", method.corporateActionAdjustment],
      ["Provider", `${data.source.provider} · API ${data.source.apiVersion}`], ["Retrieved at", data.source.retrievedAt],
    ]);
  }

  function renderIndicatorDetailQuality(item) {
    const quality = item.response.dataQuality;
    $("qualityStatus").textContent = quality.status;
    const counts = [["Observations", quality.observationCount], ["Usable IV", quality.usableIvCount], ["Invalid IV", quality.invalidIvCount]];
    const flags = Object.entries(quality.flagCounts || {});
    $("qualityContent").innerHTML = `<div class="quality-counts">${counts.map(([label, value]) => `<div class="quality-count"><small>${escapeHtml(label)}</small><strong>${formatNumber(value, 0)}</strong></div>`).join("")}</div>
      <div class="quality-flags">${flags.length ? flags.map(([flag, count]) => `<span class="flag-chip">${escapeHtml(flag)} · ${count}</span>`).join("") : '<span class="flag-chip">OK · no flags</span>'}</div>
      <p class="inline-note">${escapeHtml(quality.analyticsExclusionPolicy)}</p>`;
  }

  function renderIndicatorDetailActivity(item) {
    $("activityList").innerHTML = item.response.activity.map((event) => `<li><span class="activity-stage">${escapeHtml(event.stage)}</span><div class="activity-message"><strong>${escapeHtml(event.code)}${event.affectedObservations ? ` · ${formatNumber(event.affectedObservations, 0)}` : ""}</strong><p>${escapeHtml(event.message)}</p>${event.suggestedAction ? `<p class="activity-action">建议：${escapeHtml(event.suggestedAction)}</p>` : ""}</div></li>`).join("");
  }

  function renderIndicatorDetailDisclosures(item) {
    const context = new Set(["compare", "implied_vol", "source_metadata", "upstream_fetch", "cache", "csv", item.type]);
    const disclosures = item.response.disclosures || [];
    for (const [surface, id] of Object.entries(FRONTEND_SURFACE_IDS)) {
      if (surface === "query_builder") continue;
      renderDisclosureEntries($(id), applicableDisclosures(disclosures, context, surface));
    }
  }

  function renderIndicatorDetailWarnings(item) {
    const messages = [];
    if (item.response.dataQuality.warningBanner) messages.push(item.response.dataQuality.warningBanner);
    item.response.activity.filter((event) => ["FORWARD_RV_INCOMPLETE", "LARGE_SURFACE_RESULT"].includes(event.code)).forEach((event) => messages.push(event.message));
    $("warningBanner").classList.toggle("is-hidden", messages.length === 0);
    $("warningBanner").innerHTML = messages.map((message) => `<strong>WARNING</strong> · ${escapeHtml(message)}`).join("<br>");
    const missing = item.response.series.filter((point) => point.qualityFlags.some((flag) => ["MISSING_IV", "MATURITY_MISMATCH", "STRIKE_MISMATCH"].includes(flag)));
    $("coordinateHint").classList.toggle("is-hidden", missing.length === 0);
    $("coordinateHint").innerHTML = missing.length ? `<strong>精确坐标缺失：</strong>${missing.length} 个日期没有请求坐标的数据；系统没有使用邻近值。` : "";
  }

  function indicatorValueKey(type) {
    return { implied_vol: "impliedVol", realized_vol: "realizedVol", spot: "spot", forward: "forward" }[type];
  }

  function coordinateRequestLabel(request) {
    if (request.strike_rule === "fixed") return `${request.maturity_rule} ${request.low_fixed_maturity} · strike ${request.low_fixed_strike}`;
    if (request.strike_rule === "delta") return `${request.low_maturity} · delta ${request.low_delta_strike}`;
    const basis = request.strike_rule === "relative_to_forward" ? "K/F" : "K/S";
    const maturity = request.low_maturity || `${request.maturity_rule} ${request.low_fixed_maturity}`;
    return `${maturity} · ${basis} ${request.low_strike}%`;
  }

  async function downloadSelectedCsv() {
    const item = indicatorState.items.find((candidate) => candidate.id === indicatorState.selectedDetailId && candidate.request);
    if (!item) return;
    try {
      const response = await apiFetch(state.capabilities.endpoints.compareCsv, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(item.request),
      });
      const safeLabel = item.type.replaceAll(/[^a-z0-9_-]/gi, "_");
      saveBlob(await response.blob(), `${item.request.volatilityRequest.code}_${safeLabel}_compare.csv`);
    } catch (error) {
      showIndicatorFormError(`CSV 生成失败：${error.payload?.message || error.message}`);
    }
  }

  function indicatorTrace(item) {
    const points = indicatorState.seriesIndex.get(item.id).points;
    const flagsByDate = new Map((item.response?.series || []).map((point) => [point.date, point.qualityFlags.join(", ")]));
    return {
      type: "scatter",
      mode: "lines",
      x: points.map((point) => point.date),
      y: points.map((point) => point.value),
      name: indicatorLabel(item),
      text: points.map((point) => flagsByDate.get(point.date) || (item.type === "derived" ? "derived" : "")),
      hovertemplate: "%{x}<br>%{y:.4f}<br>%{text}<extra>%{fullData.name}</extra>",
      line: { color: itemColor(item), width: 2, dash: item.type === "derived" ? "dot" : "solid" },
      // Only volatility points share the left axis; prices, ratios and mixed-unit
      // results go right so a ratio around 1 cannot flatten the vol scale.
      yaxis: indicatorUnit(item) === "vol" ? "y" : "y2",
      connectgaps: false,
    };
  }

  // ------------------------------------------------------- range statistics table

  function restoreStatsColumns() {
    let stored = [];
    try {
      const raw = JSON.parse(localStorage.getItem(STATS_STORAGE_KEY) || "null");
      if (raw?.version === 1 && Array.isArray(raw.columns)) stored = raw.columns;
    } catch (error) {
      showIndicatorFormError(`无法读取统计列设置：${error.message}`);
    }
    const known = new Map(STAT_COLUMNS.map((column) => [column.id, column]));
    const ordered = [];
    const seen = new Set();
    for (const entry of stored) {
      if (!known.has(entry?.id) || seen.has(entry.id)) continue;
      seen.add(entry.id);
      ordered.push({ id: entry.id, visible: entry.visible !== false });
    }
    // Columns added after the user saved their layout appear at the end, using that
    // column's own default — this is also what a first-ever visit falls through to.
    for (const column of STAT_COLUMNS) {
      if (!seen.has(column.id)) ordered.push({ id: column.id, visible: column.defaultVisible !== false });
    }
    indicatorState.statsColumns = ordered;
  }

  function persistStatsColumns() {
    try {
      localStorage.setItem(STATS_STORAGE_KEY, JSON.stringify({ version: 1, columns: indicatorState.statsColumns }));
    } catch (error) {
      showIndicatorFormError(`浏览器无法保存统计列设置：${error.message}`);
    }
  }

  function visibleStatsColumns() {
    const known = new Map(STAT_COLUMNS.map((column) => [column.id, column]));
    return indicatorState.statsColumns.filter((entry) => entry.visible).map((entry) => known.get(entry.id));
  }

  function bindStatsColumnControls() {
    $("statsColumnList").addEventListener("change", (event) => {
      const toggle = event.target.closest("[data-column-toggle]");
      if (!toggle) return;
      const entry = indicatorState.statsColumns.find((column) => column.id === toggle.dataset.columnToggle);
      if (!entry) return;
      entry.visible = toggle.checked;
      persistStatsColumns();
      renderStatsColumnConfig();
      renderIndicatorStats();
    });
    $("statsColumnList").addEventListener("click", (event) => {
      const move = event.target.closest("[data-column-move]");
      if (!move) return;
      const index = indicatorState.statsColumns.findIndex((column) => column.id === move.dataset.columnId);
      const target = move.dataset.columnMove === "up" ? index - 1 : index + 1;
      if (index < 0 || target < 0 || target >= indicatorState.statsColumns.length) return;
      const columns = indicatorState.statsColumns;
      [columns[index], columns[target]] = [columns[target], columns[index]];
      persistStatsColumns();
      renderStatsColumnConfig();
      renderIndicatorStats();
    });
    $("statsColumnsResetButton").addEventListener("click", () => {
      indicatorState.statsColumns = STAT_COLUMNS.map((column) => ({ id: column.id, visible: column.defaultVisible !== false }));
      persistStatsColumns();
      renderStatsColumnConfig();
      renderIndicatorStats();
    });
    $("statsWidthResetButton").addEventListener("click", () => {
      indicatorState.columnWidths = {};
      persistWorkspace();
      renderIndicatorStats();
    });
    $("indicatorStatsHead").addEventListener("pointerdown", startColumnResize);
    bindStatsDragControls();
  }

  // Columns (indicators) and rows (statistics) can both be dragged into a new order.
  // Reordering a column reorders the indicators themselves, so the chart legends and the
  // saved list follow suit rather than drifting out of step with the table.
  function bindStatsDragControls() {
    const table = $("indicatorStatsTable");
    table.addEventListener("dragstart", (event) => {
      // Only the inner handle is draggable, so grabbing the resize divider — a sibling —
      // can never start a reorder. The body class is a second line of defence.
      const cell = event.target.closest("[data-drag-handle]")?.closest("[data-drag-column], [data-drag-row]");
      if (!cell || document.body.classList.contains("is-resizing-column")) return;
      indicatorState.dragSource = cell.dataset.dragColumn
        ? { kind: "column", key: cell.dataset.dragColumn }
        : { kind: "row", key: cell.dataset.dragRow };
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", indicatorState.dragSource.key);
      cell.classList.add("is-dragging");
    });
    table.addEventListener("dragover", (event) => {
      const target = statsDropTarget(event);
      if (!target) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      for (const marked of table.querySelectorAll(".is-drop-target")) marked.classList.remove("is-drop-target");
      target.cell.classList.add("is-drop-target");
    });
    table.addEventListener("drop", (event) => {
      const target = statsDropTarget(event);
      if (!target) return;
      event.preventDefault();
      applyStatsReorder(target.key);
    });
    table.addEventListener("dragend", clearStatsDragState);
  }

  function statsDropTarget(event) {
    const source = indicatorState.dragSource;
    if (!source) return null;
    const cell = event.target.closest(source.kind === "column" ? "[data-drag-column]" : "[data-drag-row]");
    if (!cell) return null;
    const key = source.kind === "column" ? cell.dataset.dragColumn : cell.dataset.dragRow;
    return key === source.key ? null : { cell, key };
  }

  function applyStatsReorder(targetKey) {
    const source = indicatorState.dragSource;
    clearStatsDragState();
    if (!source) return;
    if (source.kind === "column") {
      const from = indicatorState.items.findIndex((item) => String(item.id) === source.key);
      const to = indicatorState.items.findIndex((item) => String(item.id) === targetKey);
      if (from < 0 || to < 0) return;
      moveWithin(indicatorState.items, from, to);
      persistWorkspace();
      refreshWorkspacePanels({ details: false });
      return;
    }
    const columns = indicatorState.statsColumns;
    const from = columns.findIndex((column) => column.id === source.key);
    const to = columns.findIndex((column) => column.id === targetKey);
    if (from < 0 || to < 0) return;
    moveWithin(columns, from, to);
    persistStatsColumns();
    renderStatsColumnConfig();
    renderIndicatorStats();
  }

  function moveWithin(list, fromIndex, toIndex) {
    const [moved] = list.splice(fromIndex, 1);
    list.splice(toIndex, 0, moved);
  }

  function clearStatsDragState() {
    indicatorState.dragSource = null;
    const table = $("indicatorStatsTable");
    for (const marked of table.querySelectorAll(".is-dragging, .is-drop-target")) {
      marked.classList.remove("is-dragging", "is-drop-target");
    }
  }

  // Dragging a header divider resizes that column. Widths live in the workspace and are
  // copied into a board when it is saved, so a board restores its own layout.
  function startColumnResize(event) {
    const handle = event.target.closest("[data-resize-key]");
    if (!handle) return;
    event.preventDefault();
    const key = handle.dataset.resizeKey;
    const column = document.querySelector(`#indicatorStatsCols col[data-column-key="${CSS.escape(key)}"]`);
    const headerCell = handle.closest("th");
    if (!column || !headerCell) return;
    const startX = event.clientX;
    // Measure the header cell: a <col> does not report a usable box of its own.
    const startWidth = headerCell.getBoundingClientRect().width;
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("is-resizing-column");
    // The header is draggable for reordering; turn that off for the duration of the
    // drag or Chrome starts a reorder instead of a resize.
    const wasDraggable = headerCell.draggable;
    headerCell.draggable = false;

    const move = (moveEvent) => {
      const width = Math.max(MIN_COLUMN_WIDTH, Math.round(startWidth + moveEvent.clientX - startX));
      indicatorState.columnWidths[key] = width;
      column.style.width = `${width}px`;
      applyStatsTableWidth();
    };
    const finish = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
      document.body.classList.remove("is-resizing-column");
      headerCell.draggable = wasDraggable;
      persistWorkspace();
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  }

  function columnWidth(key, fallback) {
    return indicatorState.columnWidths[key] || fallback;
  }

  // Columns the user has never dragged spread out to fill the panel; a dragged column
  // has its own stored width and keeps it exactly.
  function autoSeriesWidth(count, labelWidth) {
    const container = $("indicatorStatsTable")?.parentElement?.clientWidth || 0;
    if (!count || !container) return DEFAULT_SERIES_WIDTH;
    return Math.max(DEFAULT_SERIES_WIDTH, Math.floor((container - labelWidth - 2) / count));
  }

  function applyStatsTableWidth() {
    const table = $("indicatorStatsTable");
    if (!table) return;
    const total = Array.from(document.querySelectorAll("#indicatorStatsCols col"))
      .reduce((sum, column) => sum + (Number.parseFloat(column.style.width) || 0), 0);
    table.style.width = total > 0 ? `${total}px` : "";
  }

  function renderStatsColumnConfig() {
    const list = $("statsColumnList");
    if (!list) return;
    const known = new Map(STAT_COLUMNS.map((column) => [column.id, column]));
    list.innerHTML = indicatorState.statsColumns.map((entry, index) => {
      const column = known.get(entry.id);
      return `<div class="stats-column-row">
        <label><input type="checkbox" data-column-toggle="${entry.id}" ${entry.visible ? "checked" : ""} /><span>${escapeHtml(column.label)}</span></label>
        <span class="stats-column-move">
          <button type="button" data-column-move="up" data-column-id="${entry.id}" ${index === 0 ? "disabled" : ""} aria-label="上移 ${escapeHtml(column.label)}">↑</button>
          <button type="button" data-column-move="down" data-column-id="${entry.id}" ${index === indicatorState.statsColumns.length - 1 ? "disabled" : ""} aria-label="下移 ${escapeHtml(column.label)}">↓</button>
        </span>
      </div>`;
    }).join("");
    const shown = indicatorState.statsColumns.filter((entry) => entry.visible).length;
    $("statsColumnSummary").textContent = `统计项设置 · ${shown}/${indicatorState.statsColumns.length}`;
  }

  // The table is transposed: one column per indicator, one row per statistic. With two
  // dozen statistics that reads far better than a very wide row per indicator.
  function renderIndicatorStats() {
    const body = $("indicatorStatsBody");
    if (!body) return;
    const rows = visibleStatsColumns();
    const active = indicatorState.items.filter((item) => item.active);
    const series = active.map((item) => {
      const entry = indicatorState.seriesIndex.get(item.id);
      return { item, stats: summarizeSeries(entry?.points), error: entry?.error || null };
    });

    const labelWidth = columnWidth(STATS_LABEL_COLUMN, DEFAULT_LABEL_WIDTH);
    $("indicatorStatsCols").innerHTML = [
      `<col data-column-key="${STATS_LABEL_COLUMN}" style="width:${labelWidth}px" />`,
      ...series.map(({ item }) => `<col data-column-key="${item.id}" style="width:${columnWidth(String(item.id), autoSeriesWidth(series.length, labelWidth))}px" />`),
    ].join("");
    applyStatsTableWidth();

    $("indicatorStatsHead").innerHTML = `<tr>
      <th class="stats-label-cell">统计项${resizeHandle(STATS_LABEL_COLUMN)}</th>
      ${series.map(({ item, stats, error }) => `<th class="stats-series-head" data-drag-column="${item.id}">
        <span class="stats-series-name" draggable="true" data-drag-handle title="拖动可调整列顺序">${escapeHtml(indicatorLabel(item))}</span>
        ${stats ? "" : `<small class="stats-series-note">${escapeHtml(error || "当前范围内没有有效值")}</small>`}
        ${resizeHandle(String(item.id))}
      </th>`).join("")}
    </tr>`;

    if (!series.length) {
      body.innerHTML = '<tr><td class="cell-missing">没有启用中的 indicator。</td></tr>';
      $("indicatorStatsCount").textContent = "0 series";
      return;
    }
    body.innerHTML = rows.map((column) => `<tr>
      <th scope="row" class="stats-label-cell" data-drag-row="${escapeHtml(column.id)}"><span class="stats-row-name" draggable="true" data-drag-handle title="拖动可调整统计项顺序">${escapeHtml(column.label)}</span></th>
      ${series.map(({ item, stats }) => statCell(column, item, stats)).join("")}
    </tr>`).join("");
    $("indicatorStatsCount").textContent = `${series.length} series`;
  }

  function resizeHandle(key) {
    return `<span class="column-resizer" data-resize-key="${escapeHtml(key)}" role="separator" aria-label="调整列宽"></span>`;
  }

  function statCell(column, item, stats) {
    if (!stats) return '<td class="cell-missing">—</td>';
    if (column.id === "lane") return `<td>坐标 ${escapeHtml(item.config.chartLane)}</td>`;
    const value = stats[column.id];
    if (column.kind === "text") return `<td>${escapeHtml(value ?? "—")}</td>`;
    if (column.kind === "count") return `<td class="stat-number">${escapeHtml(formatNumber(value, 0))}</td>`;
    if (column.kind === "percentile" || column.kind === "zscore") {
      if (value === null || value === undefined) return '<td class="cell-missing">—</td>';
      const bucket = column.kind === "percentile" ? percentileBucket(value) : zScoreBucket(value);
      const text = column.kind === "percentile" ? `${formatFixed(value, 1)}%` : formatFixed(value, 2);
      return `<td class="heat-cell ${bucket}">${escapeHtml(text)}</td>`;
    }
    if (value === null || value === undefined) return '<td class="cell-missing">—</td>';
    if (column.kind === "percent") return `<td class="stat-number">${escapeHtml(`${formatFixed(value, 1)}%`)}</td>`;
    // Ratios (z-score, skew, kurtosis, autocorrelation) are unitless by construction.
    if (column.kind === "ratio") return `<td class="stat-number">${escapeHtml(formatFixed(value, 2))}</td>`;
    const text = `${formatFixed(value, valueDigits(item))}${unitSuffix(item)}`;
    const sign = column.kind === "signed" && value !== 0 ? (value > 0 ? " stat-up" : " stat-down") : "";
    const prefix = column.kind === "signed" && value > 0 ? "+" : "";
    return `<td class="stat-number${sign}">${escapeHtml(`${prefix}${text}`)}</td>`;
  }

  // Statistics columns keep a fixed decimal count so the numbers stay column-aligned,
  // unlike formatNumber which drops trailing zeros.
  function formatFixed(value, digits) {
    return new Intl.NumberFormat("zh-HK", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
  }

  // Volatility reads best at one decimal; prices need two and ratios three.
  function valueDigits(item) {
    const unit = indicatorUnit(item);
    if (unit === "vol") return 1;
    return unit === "price" ? 2 : 3;
  }

  function percentileBucket(value) {
    if (value >= 80) return "heat-high";
    if (value >= 60) return "heat-mid-high";
    if (value > 40) return "heat-mid";
    if (value > 20) return "heat-mid-low";
    return "heat-low";
  }

  // Same five-step scale as the percentile, read in standard deviations.
  function zScoreBucket(value) {
    if (value >= 2) return "heat-high";
    if (value >= 1) return "heat-mid-high";
    if (value > -1) return "heat-mid";
    if (value > -2) return "heat-mid-low";
    return "heat-low";
  }

  function summarizeSeries(points) {
    if (!points) return null;
    const usable = points
      .filter((point) => point.value !== null && point.value !== undefined)
      .sort((left, right) => (left.date < right.date ? -1 : left.date > right.date ? 1 : 0));
    if (!usable.length) return null;
    const values = usable.map((point) => point.value);
    const sorted = [...values].sort((left, right) => left - right);
    const count = values.length;
    const mean = average(values);
    const variance = count > 1
      ? values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (count - 1)
      : 0;
    const stdDev = Math.sqrt(variance);
    const latest = usable.at(-1);
    const min = sorted[0];
    const max = sorted.at(-1);
    const maxIndex = values.indexOf(max);
    const minIndex = values.indexOf(min);
    const steps = values.slice(1).map((value, index) => value - values[index]);
    const mean20 = average(values.slice(-20));
    return {
      count,
      latest: latest.value,
      latestDate: latest.date,
      min,
      max,
      range: max - min,
      minDate: usable[minIndex].date,
      maxDate: usable[maxIndex].date,
      // How many observations ago the extreme happened; 0 means it is the latest point.
      sessionsSinceMax: count - 1 - maxIndex,
      sessionsSinceMin: count - 1 - minIndex,
      mean,
      mean20,
      mean60: average(values.slice(-60)),
      vsMean20: mean20 === null ? null : latest.value - mean20,
      median: quantile(sorted, 0.5),
      p25: quantile(sorted, 0.25),
      p75: quantile(sorted, 0.75),
      stdDev,
      iqr: quantile(sorted, 0.75) - quantile(sorted, 0.25),
      percentile: (sorted.filter((value) => value <= latest.value).length / count) * 100,
      zScore: stdDev > 0 ? (latest.value - mean) / stdDev : null,
      change1: changeOverSessions(values, 1),
      change5: changeOverSessions(values, 5),
      change20: changeOverSessions(values, 20),
      change60: changeOverSessions(values, 60),
      largestGain: steps.length ? steps.reduce((best, step) => Math.max(best, step), -Infinity) : null,
      largestDrop: steps.length ? steps.reduce((best, step) => Math.min(best, step), Infinity) : null,
      meanAbsChange: steps.length ? average(steps.map(Math.abs)) : null,
      positiveShare: (values.filter((value) => value > 0).length / count) * 100,
      skewness: sampleSkewness(values, mean, stdDev),
      kurtosis: sampleKurtosis(values, mean, stdDev),
      autocorrelation: autocorrelationAtLag(values, mean, 1),
      autocorrelation5: autocorrelationAtLag(values, mean, 5),
      autocorrelation20: autocorrelationAtLag(values, mean, 20),
    };
  }

  function average(values) {
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  }

  function quantile(sorted, fraction) {
    if (sorted.length === 1) return sorted[0];
    const position = (sorted.length - 1) * fraction;
    const lower = Math.floor(position);
    const upper = Math.ceil(position);
    if (lower === upper) return sorted[lower];
    return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
  }

  // Lags count usable observations, so a gap in the series never silently shifts the
  // comparison onto a different trading day.
  function changeOverSessions(values, lag) {
    return values.length > lag ? values.at(-1) - values.at(-1 - lag) : null;
  }

  function sampleSkewness(values, mean, stdDev) {
    const count = values.length;
    if (count < 3 || !(stdDev > 0)) return null;
    const sum = values.reduce((total, value) => total + ((value - mean) / stdDev) ** 3, 0);
    return (count / ((count - 1) * (count - 2))) * sum;
  }

  function sampleKurtosis(values, mean, stdDev) {
    const count = values.length;
    if (count < 4 || !(stdDev > 0)) return null;
    const sum = values.reduce((total, value) => total + ((value - mean) / stdDev) ** 4, 0);
    return ((count * (count + 1)) / ((count - 1) * (count - 2) * (count - 3))) * sum
      - (3 * (count - 1) ** 2) / ((count - 2) * (count - 3));
  }

  function autocorrelationAtLag(values, mean, lag) {
    if (values.length < lag + 2) return null;
    let numerator = 0;
    let denominator = 0;
    for (let index = 0; index < values.length; index += 1) {
      const centered = values[index] - mean;
      denominator += centered * centered;
      if (index >= lag) numerator += centered * (values[index - lag] - mean);
    }
    return denominator > 0 ? numerator / denominator : null;
  }

  function renderIndicatorWarnings(active) {
    const errors = active.filter((item) => item.status === "error");
    const invalid = active
      .filter((item) => item.type === "implied_vol")
      .reduce((count, item) => count + (item.response?.dataQuality?.invalidIvCount || 0), 0);
    const warning = $("timeseriesWarning");
    const messages = [];
    if (errors.length) messages.push(`${errors.length} 个激活指标加载失败；查看左侧指标卡的原始错误。`);
    if (invalid) messages.push(`${invalid} 个非正/无效 IV 点保留 raw value，但图中为空且不连接。`);
    if (!messages.length) {
      warning.classList.add("is-hidden");
      warning.textContent = "";
      return;
    }
    warning.textContent = messages.join(" ");
    warning.classList.remove("is-hidden");
  }

  function showIndicatorFormError(message) {
    $("indicatorFormError").textContent = message;
    $("indicatorFormError").classList.remove("is-hidden");
  }

  function hideIndicatorFormError() {
    $("indicatorFormError").classList.add("is-hidden");
  }

  window.volcurveCompareDetails = { downloadSelectedCsv };
  window.addEventListener("DOMContentLoaded", initIndicatorBuilder);
})();
