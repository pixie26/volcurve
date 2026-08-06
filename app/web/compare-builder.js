"use strict";

(() => {
  const STORAGE_KEY = "volcurve.compare.workspace.v1";
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
  };

  const TYPE_LABELS = {
    implied_vol: "Implied volatility",
    realized_vol: "Realized volatility",
    spot: "Spot · 原始未复权",
    forward: "Forward",
  };
  const PALETTE = ["#0f7554", "#3557a4", "#d66a2d", "#8c6bb1", "#bf3d5d", "#4e8f9c", "#8e7b28"];

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
    };
  }

  function initIndicatorBuilder() {
    $("indicatorType").addEventListener("change", (event) => {
      const next = defaultDraft(event.target.value);
      next.instrumentCode = indicatorState.draft.instrumentCode;
      next.chartLane = indicatorState.draft.chartLane;
      indicatorState.draft = next;
      indicatorState.discovery = null;
      renderIndicatorConfig();
    });
    $("addIndicatorButton").addEventListener("click", addIndicator);
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
    $("instrumentCode").addEventListener("change", () => {
      indicatorState.draft.instrumentCode = $("instrumentCode").value.trim();
      persistWorkspace();
      renderIndicatorConfig();
    });
    document.querySelectorAll('input[name="queryKind"]').forEach((input) => {
      input.addEventListener("change", syncWorkspaceMode);
    });
    window.addEventListener("volcurve:capabilities", () => {
      renderIndicatorConfig();
      renderIndicatorChart();
      if (indicatorState.restorePending) {
        indicatorState.restorePending = false;
        refreshActiveIndicators();
      }
    });
    restoreWorkspace();
    syncWorkspaceMode();
    renderIndicatorConfig();
    renderSavedIndicators();
    renderIndicatorChart();
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
    renderIndicatorChart();
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
          status: "stale",
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
        },
        selectedDetailId: indicatorState.selectedDetailId,
        chartCount: indicatorState.chartCount,
        items: indicatorState.items.map((item) => ({
          id: item.id,
          type: item.type,
          config: item.config,
          active: item.active,
        })),
      }));
    } catch (error) {
      showIndicatorFormError(`浏览器无法保存 indicators：${error.message}`);
    }
  }

  function renderIndicatorConfig() {
    const draft = indicatorState.draft;
    const config = $("indicatorConfig");
    if (!config) return;
    let html = "";
    const placement = indicatorPlacementFields(draft);
    if (draft.type === "implied_vol") {
      html = `${placement}${requestSystemFields(draft)}${maturityModeField(draft)}${maturityValueField(draft)}${strikeFields(draft)}${listedDiscoveryPanel(draft)}`;
      $("indicatorBuilderNote").textContent = "IV 使用精确 maturity + strike 坐标。Vol convention 与 layout 都是 BNP 请求字段；缺失值不会换成邻近坐标。";
    } else if (draft.type === "realized_vol") {
      html = `${placement}${requestSystemFields(draft)}<div class="field-grid two config-grid">
        <label class="field"><span>Window · sessions</span><input data-draft="rvWindow" type="number" min="2" step="1" list="rvWindowOptions" value="${escapeHtml(draft.rvWindow)}" /></label>
        <label class="field"><span>Alignment</span><select data-draft="rvAlignment"><option value="trailing" ${draft.rvAlignment === "trailing" ? "selected" : ""}>Trailing</option><option value="forward" ${draft.rvAlignment === "forward" ? "selected" : ""}>Forward</option></select></label>
      </div>`;
      $("indicatorBuilderNote").textContent = "RV 接受任意 ≥2 的整数窗口，不取最近档位。Spot 来自 BNP IV 响应，因此独立 RV 会明确使用 3M K/F 100% 作为取数载体；该坐标不进入 RV 公式。";
    } else if (draft.type === "spot") {
      html = `${placement}${requestSystemFields(draft)}<div class="system-default-card"><strong>无需额外参数</strong><span>BNP 原始未复权 spot / price-return source</span></div>`;
      $("indicatorBuilderNote").textContent = "当前 Cortex 数据路径把 spot 放在 IV response 内；系统用 3M K/F 100% 请求承载 spot，并在指标卡中明示。不会把该参考 IV 当作用户选择的指标。";
    } else {
      html = `${placement}${requestSystemFields(draft)}${maturityModeField(draft)}${maturityValueField(draft)}${listedDiscoveryPanel(draft)}`;
      $("indicatorBuilderNote").textContent = "Forward 按所选 maturity 读取 BNP forward curve；系统用 K/F 100% 作为响应载体。该 moneyness 不改变同一期限的 forward 值。";
    }
    config.innerHTML = html;
    bindDraftFields();
    bindIndicatorDiscovery();
  }

  function indicatorPlacementFields(draft) {
    const chartOptions = Array.from({ length: indicatorState.chartCount }, (_, index) => index + 1)
      .map((lane) => `<option value="${lane}" ${String(lane) === draft.chartLane ? "selected" : ""}>坐标 ${lane}</option>`).join("");
    return `<div class="field-grid two config-grid indicator-placement-fields">
      <label class="field"><span>Indicator instrument</span><input data-draft="instrumentCode" value="${escapeHtml(draft.instrumentCode)}" list="instrumentOptions" autocomplete="off" /><small>每个 indicator 独立保存标的。</small></label>
      <label class="field"><span>Chart</span><select data-draft="chartLane">${chartOptions}</select><small>可在保存卡片中随时移动。</small></label>
    </div>`;
  }

  function requestSystemFields(draft) {
    return `<div class="field-grid two config-grid request-system-fields">
      <label class="field"><span>Vol convention</span><select data-draft="volatilityConvention"><option value="bsVol" ${draft.volatilityConvention === "bsVol" ? "selected" : ""}>bsVol</option><option value="bnppVol" ${draft.volatilityConvention === "bnppVol" ? "selected" : ""}>bnppVol</option></select><small>BNP 字段；通常只有 bsVol 可用。</small></label>
      <label class="field"><span>Layout</span><select data-draft="layout"><option value="matrix" ${draft.layout === "matrix" ? "selected" : ""}>Matrix</option><option value="vector" ${draft.layout === "vector" ? "selected" : ""}>Vector</option></select><small>BNP 返回结构；数值语义不变。</small></label>
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
      return `<label class="field field-wide"><span>Sliding maturity</span><input data-draft="slidingMaturity" value="${escapeHtml(draft.slidingMaturity)}" list="indicatorMaturityOptions" autocomplete="off" /><datalist id="indicatorMaturityOptions">${optionList(maturities)}</datalist><small>可键盘输入，但必须是 BNP OpenAPI 列出的 tenor；不支持的值会在本地明确拒绝。</small></label>`;
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
      coordinate = `<label class="field field-wide"><span>Put / Call delta</span><input data-draft="delta" value="${escapeHtml(draft.delta)}" list="indicatorDeltaOptions" autocomplete="off" /><datalist id="indicatorDeltaOptions">${optionList(state.capabilities?.deltaStrikes || [])}</datalist><small>Delta 只支持 sliding maturity 和 BNP 官方 delta codes。</small></label>`;
    } else {
      coordinate = `<label class="field field-wide"><span>Absolute strike</span><input data-draft="absoluteStrike" type="number" min="0.000001" step="any" value="${escapeHtml(draft.absoluteStrike)}" /><small>允许任意正数；不存在的精确 strike 返回缺失，不自动取 listed 邻近值。</small></label>`;
    }
    const combinationNote = fixedMaturity ? "" : "<small>BNP API 不支持 Sliding maturity + Absolute strike；系统不会自动把 3M 转成邻近 expiry。</small>";
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
      result = '<p class="coordinate-discovery-status">正在向 BNP 请求该观察日的 listed surface…</p>';
    } else if (discovery?.status === "error") {
      result = `<p class="coordinate-discovery-error">${escapeHtml(discovery.message)}</p>`;
    } else if (discovery?.status === "ready") {
      const expiries = discovery.snapshot.maturities.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
      const needsStrike = draft.type === "implied_vol" && draft.strikeKind === "absolute";
      result = `<div class="coordinate-grid discovery-selectors">
        <label class="field"><span>Available expiry</span><select id="indicatorAvailableExpiry"><option value="">请选择实际 expiry</option>${expiries}</select></label>
        ${needsStrike ? '<label class="field"><span>Available strike</span><select id="indicatorAvailableStrike" disabled><option value="">先选择 expiry</option></select></label>' : ""}
      </div><p id="indicatorCoordinateStatus" class="coordinate-discovery-status">BNP 返回 ${discovery.snapshot.maturities.length} 个 expiry；系统没有自动选择。</p>
      <button id="applyIndicatorCoordinate" class="secondary-button discovery-apply" type="button" disabled>应用所选 listed 坐标</button>`;
    }
    return `<section class="coordinate-discovery" aria-label="BNP listed 坐标发现">
      <div class="coordinate-discovery-heading"><strong>向 BNP 加载实际 listed 坐标</strong><small>手输仍然允许；加载结果只供明确选择，不替代当前输入。</small></div>
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
      if (!snapshot) throw new Error("BNP 在该观察日没有返回 listed surface。");
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

  function addIndicator() {
    hideIndicatorFormError();
    try {
      validateScope(indicatorState.draft);
      validateDraft(indicatorState.draft);
    } catch (error) {
      showIndicatorFormError(error.message);
      return;
    }
    const item = {
      id: indicatorState.nextId++,
      type: indicatorState.draft.type,
      config: structuredClone(indicatorState.draft),
      active: true,
      status: "queued",
      response: null,
      request: null,
      error: null,
    };
    indicatorState.items.push(item);
    indicatorState.selectedDetailId = item.id;
    persistWorkspace();
    renderSavedIndicators();
    fetchIndicator(item);
  }

  function validateScope(config) {
    if (!state.capabilities) throw new Error("Capability registry 尚未载入，请稍后重试。");
    if (!config?.instrumentCode?.trim()) throw new Error("请输入该 indicator 的 instrument code。");
    if (!$("startDate").value || !$("endDate").value) throw new Error("请选择完整日期范围。");
    if ($("startDate").value > $("endDate").value) throw new Error("开始日期不能晚于结束日期。");
  }

  function validateDraft(draft) {
    if (["implied_vol", "forward"].includes(draft.type)) {
      if (draft.maturityMode === "sliding") {
        const supported = draft.strikeKind === "delta"
          ? state.capabilities.deltaMaturities
          : state.capabilities.slidingMaturities;
        if (!supported.includes(draft.slidingMaturity)) {
          throw new Error(`BNP OpenAPI 不接受 sliding maturity ${draft.slidingMaturity || "(空)"}；请输入官方 tenor。`);
        }
      } else if (!validIsoDate(draft.expiry)) {
        throw new Error("请输入合法的 fixed/listed expiry 日期。");
      }
    }
    if (draft.type === "implied_vol") {
      if (draft.strikeKind === "percentage") {
        const value = Number(draft.moneyness);
        if (!state.capabilities.moneynessLevels.some((level) => Number(level) === value)) {
          throw new Error(`BNP OpenAPI 不接受 moneyness ${draft.moneyness || "(空)"}；请输入官方离散档位。`);
        }
      } else if (draft.strikeKind === "delta") {
        if (draft.maturityMode !== "sliding" || !state.capabilities.deltaStrikes.includes(draft.delta)) {
          throw new Error("Delta 只接受 sliding maturity 与 BNP 官方 delta code。");
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
    item.status = "loading";
    item.error = null;
    renderSavedIndicators();
    renderIndicatorChart();
    renderIndicatorDetails();
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
    renderSavedIndicators();
    renderIndicatorChart();
    renderIndicatorDetails();
  }

  async function refreshActiveIndicators() {
    hideIndicatorFormError();
    await Promise.all(indicatorState.items.filter((item) => item.active).map(fetchIndicator));
  }

  function invalidateIndicators() {
    indicatorState.discovery = null;
    for (const item of indicatorState.items) {
      item.status = "stale";
      item.response = null;
      item.error = null;
    }
    persistWorkspace();
    renderSavedIndicators();
    renderIndicatorChart();
    renderIndicatorDetails();
  }

  function handleSavedIndicatorChange(event) {
    const laneSelect = event.target.closest("[data-indicator-lane]");
    if (laneSelect) {
      const item = indicatorState.items.find((candidate) => candidate.id === Number(laneSelect.dataset.indicatorLane));
      if (!item) return;
      item.config.chartLane = laneSelect.value;
      persistWorkspace();
      renderSavedIndicators();
      renderIndicatorChart();
      return;
    }
    const toggle = event.target.closest("[data-indicator-toggle]");
    if (!toggle) return;
    const item = indicatorState.items.find((candidate) => candidate.id === Number(toggle.dataset.indicatorToggle));
    if (!item) return;
    item.active = toggle.checked;
    persistWorkspace();
    renderSavedIndicators();
    renderIndicatorChart();
    if (item.active && !item.response) fetchIndicator(item);
  }

  function addChartLane() {
    if (indicatorState.chartCount >= MAX_CHARTS) return;
    indicatorState.chartCount += 1;
    indicatorState.draft.chartLane = String(indicatorState.chartCount);
    persistWorkspace();
    renderIndicatorConfig();
    renderSavedIndicators();
    renderIndicatorChart();
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
    renderIndicatorConfig();
    renderSavedIndicators();
    renderIndicatorChart();
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
    const deleteButton = event.target.closest("[data-indicator-delete]");
    if (!deleteButton) return;
    const deletedId = Number(deleteButton.dataset.indicatorDelete);
    indicatorState.items = indicatorState.items.filter((item) => item.id !== deletedId);
    if (indicatorState.selectedDetailId === deletedId) indicatorState.selectedDetailId = null;
    persistWorkspace();
    renderSavedIndicators();
    renderIndicatorChart();
    renderIndicatorDetails();
  }

  function renderSavedIndicators() {
    $("indicatorCount").textContent = String(indicatorState.items.length);
    if (!indicatorState.items.length) {
      $("savedIndicators").innerHTML = '<p class="empty-list-copy">尚未添加指标。</p>';
      return;
    }
    const laneOptions = (selected) => Array.from({ length: indicatorState.chartCount }, (_, index) => index + 1).map((lane) => `<option value="${lane}" ${String(lane) === String(selected) ? "selected" : ""}>坐标 ${lane}</option>`).join("");
    $("savedIndicators").innerHTML = indicatorState.items.map((item) => `<article class="saved-indicator ${item.active ? "is-active" : ""}">
      <label class="indicator-toggle"><input type="checkbox" data-indicator-toggle="${item.id}" ${item.active ? "checked" : ""}/><span aria-hidden="true"></span></label>
      <div class="saved-indicator-copy"><strong>${escapeHtml(indicatorLabel(item))}</strong><small>${escapeHtml(indicatorDetail(item))}</small><em class="indicator-status status-${item.status}">${escapeHtml(indicatorStatus(item))}</em>${item.error ? `<p>${escapeHtml(item.error)}</p>` : ""}</div>
      <div class="saved-indicator-actions"><select class="indicator-lane-select" data-indicator-lane="${item.id}" aria-label="${escapeHtml(indicatorLabel(item))} 所属坐标">${laneOptions(item.config.chartLane)}</select><button class="view-indicator-detail" type="button" data-indicator-detail="${item.id}" ${item.response ? "" : "disabled"}>查看详情</button><button class="delete-indicator" type="button" data-indicator-delete="${item.id}" aria-label="删除 ${escapeHtml(indicatorLabel(item))}">×</button></div>
    </article>`).join("");
  }

  function indicatorLabel(item) {
    const config = item.config;
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
    if (item.type === "realized_vol") return `${placement} · price-return RV · spot via reference 3M K/F 100% · ${wire} carrier`;
    if (item.type === "spot") return `${placement} · BNP spot · 未复权 · reference 3M K/F 100% · ${wire} carrier`;
    if (item.type === "forward") return `${placement} · BNP forward curve · K/F 100% response carrier · ${wire}`;
    return `${placement} · BNP ${wire} · exact coordinate · no substitution`;
  }

  function indicatorStatus(item) {
    return { queued: "等待加载", loading: "加载中", ready: "已加载", stale: "范围已变化，待刷新", error: "加载失败" }[item.status] || item.status;
  }

  function renderIndicatorChart() {
    if (!window.Plotly || !$("indicatorCharts")) return;
    renderChartShells();
    const active = indicatorState.items.filter((item) => item.active);
    const ready = active.filter((item) => item.status === "ready" && item.response);
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
        xaxis: { title: "Observation date", type: "date", range: start && end ? [start, end] : undefined, gridcolor: "#e8ebe4", showspikes: true, spikemode: "across", spikesnap: "cursor", spikecolor: "#6f7f76", spikethickness: 1 },
        yaxis: { title: "Volatility (%)", gridcolor: "#e8ebe4", zeroline: false },
        yaxis2: { title: "Price / forward", overlaying: "y", side: "right", showgrid: false, zeroline: false },
        annotations,
        uirevision: `chart-${lane}-${start}-${end}`,
      }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d"] })).then(() => bindChartSync(div));
    }
    const instruments = new Set(indicatorState.items.map((item) => item.config.instrumentCode));
    $("timeseriesStatus").textContent = `${indicatorState.chartCount}/${MAX_CHARTS} charts · ${active.length} active`;
    $("timeseriesTitle").textContent = indicatorState.items.length ? `${instruments.size} instruments · ${indicatorState.items.length} indicators` : "空白时序图";
    $("timeseriesSubtitle").textContent = `${start || "—"} → ${end || "—"} · 同日 hover 与 X 轴缩放在所有坐标间同步。`;
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
        <div class="panel-heading"><div><p class="eyebrow">CHART ${lane}</p><h3>坐标 ${lane}</h3></div><div class="chart-pane-actions"><span id="chartPaneCount-${lane}" class="chart-pane-count">0 active</span><span class="axis-note">左轴：波动率 % · 右轴：价格 · 框选缩放</span>${removeButton}</div></div>
        <div id="indicatorChart-${lane}" class="chart timeseries-chart"></div>
      </article>`;
    }).join("");
  }

  function bindChartSync(div) {
    if (!div?.on || div.dataset.syncBound === "true") return;
    div.dataset.syncBound = "true";
    div.on("plotly_hover", (event) => syncHover(div, event.points?.[0]?.x));
    div.on("plotly_unhover", () => clearSynchronizedHover(div));
    div.on("plotly_relayout", (event) => syncXZoom(div, event));
  }

  function chartDivs() {
    return Array.from(document.querySelectorAll("#indicatorCharts .timeseries-chart"));
  }

  function syncHover(source, xValue) {
    if (indicatorState.hoverSyncing || xValue === undefined || xValue === null) return;
    indicatorState.hoverSyncing = true;
    for (const div of chartDivs()) {
      if (div === source || !Array.isArray(div.data)) continue;
      const points = [];
      div.data.forEach((trace, curveNumber) => {
        const pointNumber = Array.isArray(trace.x) ? trace.x.findIndex((value) => String(value) === String(xValue)) : -1;
        if (pointNumber >= 0) points.push({ curveNumber, pointNumber });
      });
      if (points.length) Plotly.Fx.hover(div, points);
    }
    setTimeout(() => { indicatorState.hoverSyncing = false; }, 0);
  }

  function clearSynchronizedHover(source) {
    if (indicatorState.hoverSyncing) return;
    indicatorState.hoverSyncing = true;
    for (const div of chartDivs()) if (div !== source) Plotly.Fx.unhover(div);
    setTimeout(() => { indicatorState.hoverSyncing = false; }, 0);
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
    const series = item.response.series;
    const valueKey = { implied_vol: "impliedVol", realized_vol: "realizedVol", spot: "spot", forward: "forward" }[item.type];
    return {
      type: "scatter",
      mode: "lines",
      x: series.map((point) => point.date),
      y: series.map((point) => point[valueKey]),
      name: indicatorLabel(item),
      text: series.map((point) => point.qualityFlags.join(", ")),
      hovertemplate: "%{x}<br>%{y:.4f}<br>%{text}<extra>%{fullData.name}</extra>",
      line: { color: PALETTE[(item.id - 1) % PALETTE.length], width: 2 },
      yaxis: ["spot", "forward"].includes(item.type) ? "y2" : "y",
      connectgaps: false,
    };
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
