"use strict";

// Thin controller for the Time Series workspace.  State/persistence, request/series logic,
// pure analytics and rendering live in compare-workspace/request/core/render respectively.
function on(id, event, handler) {
  const element = $(id);
  if (!element) {
    console.warn(`volcurve: 找不到 #${id}，该控件未绑定（页面与脚本版本可能不一致，请强制刷新）。`);
    return;
  }
  element.addEventListener(event, handler);
}

function initIndicatorBuilder() {
  on("indicatorType", "change", (event) => {
    const next = defaultDraft(event.target.value);
    next.instrumentCode = indicatorState.draft.instrumentCode;
    next.chartLane = indicatorState.draft.chartLane;
    indicatorState.draft = next;
    indicatorState.discovery = null;
    renderScopeFields();
    renderIndicatorConfig();
  });
  on("addIndicatorButton", "click", submitIndicator);
  on("cancelEditButton", "click", cancelEditing);
  on("refreshIndicatorsButton", "click", () => refreshActiveIndicators());
  on("forceRefreshIndicatorsButton", "click", forceRefreshActiveIndicators);
  on("bulkModeButton", "click", () => toggleBulkMode());
  on("bulkMoveButton", "click", () => applyBulkInstrument({ copy: false }));
  on("bulkCopyButton", "click", () => applyBulkInstrument({ copy: true }));
  on("bulkBar", "click", handleBulkBarClick);
  on("bulkInstrumentSearchButton", "click", searchBulkInstruments);
  on("bulkInstrumentCode", "input", clearBulkInstrumentSelection);
  on("bulkInstrumentCode", "keydown", handleBulkInstrumentKeydown);
  on("bulkInstrumentResults", "click", handleBulkInstrumentResultClick);
  on("bulkUnderlyingTab", "click", () => setBulkEditMode("underlying"));
  on("bulkMaturityTab", "click", () => setBulkEditMode("maturity"));
  on("bulkMaturityMode", "change", renderBulkMaturityControls);
  on("bulkSlidingMaturity", "change", syncBulkMaturityButtons);
  on("bulkFixedMaturity", "change", syncBulkMaturityButtons);
  on("bulkMaturityMoveButton", "click", () => applyBulkMaturity({ copy: false }));
  on("bulkMaturityCopyButton", "click", () => applyBulkMaturity({ copy: true }));
  on("addChartButton", "click", addChartLane);
  on("indicatorCharts", "click", handleChartStackClick);
  on("indicatorCharts", "dblclick", handleChartNameDoubleClick);
  on("indicatorCharts", "dragstart", handleChartDragStart);
  on("indicatorCharts", "dragover", handleChartDragOver);
  on("indicatorCharts", "drop", handleChartDrop);
  on("indicatorCharts", "dragend", clearChartDragState);
  on("savedIndicators", "change", handleSavedIndicatorChange);
  on("savedIndicators", "click", handleSavedIndicatorClick);
  on("detailIndicatorSelect", "change", (event) => {
    indicatorState.selectedDetailId = Number(event.target.value);
    persistWorkspace();
    renderIndicatorDetails();
  });
  on("qualityContent", "click", handleQualityIssueClick);
  for (const id of ["startDate", "endDate"]) on(id, "change", invalidateIndicators);

  document.querySelectorAll('input[name="queryKind"]').forEach((input) => {
    input.addEventListener("change", syncWorkspaceMode);
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest("#bulkInstrumentResults, #bulkInstrumentCode, #bulkInstrumentSearchButton")) {
      hideBulkInstrumentResults();
    }
  });
  window.addEventListener("volcurve:capabilities", () => {
    renderIndicatorConfig();
    refreshWorkspacePanels({ details: false });
    if (indicatorState.restorePending) {
      indicatorState.restorePending = false;
      refreshActiveIndicators();
    }
  });

  const steps = [
    ["日期模式", bindDateModeControls],
    ["标的与坐标", bindScopeFields],
    ["boards", bindBoardControls],
    ["统计列", bindStatsColumnControls],
    ["统计列配置", restoreStatsColumns],
    ["boards 读取", restoreBoards],
    ["工作区读取", restoreWorkspace],
    ["日期范围", syncSlidingRange],
    ["日期模式渲染", renderDateMode],
    ["模式切换", syncWorkspaceMode],
    ["指标表单", renderIndicatorConfig],
    ["编辑状态", renderBuilderMode],
    ["统计列渲染", renderStatsColumnConfig],
    ["boards 渲染", renderBoards],
  ];
  for (const [name, step] of steps) {
    try { step(); }
    catch (error) { console.error(`volcurve: 「${name}」初始化失败`, error); }
  }
}

window.addEventListener("DOMContentLoaded", initIndicatorBuilder);

// VOLCURVE_COMPARE_MODULE_SPLIT_V7_5
