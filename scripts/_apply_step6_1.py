from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, found {count}")
    return text.replace(old, new, 1)


# Restore Fixed date as an intentional bulk target while keeping the main builder unchanged.
path = Path("app/web/compare-builder.js")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''    on("bulkMaturityTab", "click", () => setBulkEditMode("maturity"));
    on("bulkSlidingMaturity", "change", syncBulkMaturityButtons);
    on("bulkMaturityMoveButton", "click", () => applyBulkMaturity({ copy: false }));''',
    '''    on("bulkMaturityTab", "click", () => setBulkEditMode("maturity"));
    on("bulkMaturityMode", "change", renderBulkMaturityControls);
    on("bulkSlidingMaturity", "change", syncBulkMaturityButtons);
    on("bulkFixedMaturity", "change", syncBulkMaturityButtons);
    on("bulkMaturityMoveButton", "click", () => applyBulkMaturity({ copy: false }));''',
    "bulk bindings",
)
start = text.index("  function renderBulkMaturityControls() {")
end = text.index("  function applyBulkInstrument({ copy }) {", start)
new_block = r'''  function renderBulkMaturityControls() {
    const mode = $("bulkMaturityMode")?.value === "fixed" ? "fixed" : "sliding";
    $("bulkSlidingMaturityField")?.classList.toggle("is-hidden", mode !== "sliding");
    $("bulkFixedMaturityField")?.classList.toggle("is-hidden", mode !== "fixed");

    const items = bulkMaturityItems();
    const select = $("bulkSlidingMaturity");
    if (select && mode === "sliding") {
      const values = bulkMaturitySupportedTenors(items);
      const current = select.value;
      select.innerHTML = values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
      const preferred = values.includes(current)
        ? current
        : values.includes("3M")
          ? "3M"
          : values[0] || "";
      select.value = preferred;
    }

    const help = $("bulkMaturityHelp");
    if (help) {
      const ignored = [...indicatorState.bulkSelection]
        .map(itemById)
        .filter((item) => item && (item.type === "spot" || item.type === "realized_vol")).length;
      const suffix = ignored ? ` 另有 ${ignored} 个直接选中的 Spot/RV 没有 option tenor，会忽略。` : "";
      help.textContent = `将修改 ${items.length} 个 IV / Forward。Sliding 与 Fixed date 支持批量；Fixed date 会按精确日期请求，坐标不存在时允许后端返回 NO_DATA，不做最近期限替代。Listed expiry 暂不作为批量目标。${suffix}`;
    }
    syncBulkMaturityButtons();
  }

  function syncBulkMaturityButtons() {
    const items = bulkMaturityItems();
    const mode = $("bulkMaturityMode")?.value === "fixed" ? "fixed" : "sliding";
    const value = mode === "sliding"
      ? $("bulkSlidingMaturity")?.value || ""
      : $("bulkFixedMaturity")?.value || "";
    const enabled = items.length > 0 && Boolean(value);
    if ($("bulkMaturityMoveButton")) $("bulkMaturityMoveButton").disabled = !enabled;
    if ($("bulkMaturityCopyButton")) $("bulkMaturityCopyButton").disabled = !enabled;
  }

  function bulkMaturityCompatibility(items, mode, value) {
    if (!items.length) return "所选项里没有 IV 或 Forward 可以修改期限。";
    if (mode === "fixed") {
      if (!validIsoDate(value)) return "请选择合法的 Fixed maturity date。";
      const delta = items.filter(
        (item) => item.type === "implied_vol" && item.config.strikeKind === "delta",
      );
      if (delta.length) {
        return `有 ${delta.length} 个 Delta IV；当前数据契约只支持 Delta + Sliding maturity，不能批量改成 Fixed date。`;
      }
      return null;
    }
    const supported = bulkMaturitySupportedTenors(items);
    if (!supported.includes(value)) return `当前所选指标不支持 Sliding tenor ${value || "(空)"}。`;
    const absolute = items.filter(
      (item) => item.type === "implied_vol" && item.config.strikeKind === "absolute",
    );
    if (absolute.length) {
      return `有 ${absolute.length} 个 Absolute-strike IV；当前数据契约不支持 Absolute strike + Sliding maturity。`;
    }
    return null;
  }

  function applyMaturityToItem(item, mode, value) {
    item.config.maturityMode = mode;
    if (mode === "sliding") {
      item.config.slidingMaturity = value;
      item.config.expiry = "";
    } else {
      item.config.expiry = value;
    }
    item.status = initialStatus(item.type);
    item.response = null;
    item.request = null;
    item.error = null;
  }

  function applyBulkMaturity({ copy }) {
    hideIndicatorFormError();
    const mode = $("bulkMaturityMode")?.value === "fixed" ? "fixed" : "sliding";
    const value = mode === "sliding"
      ? $("bulkSlidingMaturity")?.value || ""
      : $("bulkFixedMaturity")?.value || "";
    const items = bulkMaturityItems();
    const problem = bulkMaturityCompatibility(items, mode, value);
    if (problem) return setBulkNote(problem, "is-error");

    const outcome = copy
      ? bulkCopyMaturity(mode, value)
      : bulkMoveMaturity(items, mode, value);
    persistWorkspace();
    refreshWorkspacePanels();
    fetchMissingDependencies();
    renderBulkMaturityControls();
    setBulkNote(outcome);
  }

  function bulkMoveMaturity(items, mode, value) {
    const renamed = items.filter((item) => indicatorAlias(item)).length;
    for (const item of items) applyMaturityToItem(item, mode, value);
    const label = mode === "fixed" ? `Fixed ${value}` : `Sliding ${value}`;
    const notes = [`已把 ${items.length} 个 IV / Forward 换成 ${label}。`];
    if (renamed) notes.push(`其中 ${renamed} 个保留了原有别名，如不再合适请双击列头改名。`);
    notes.push(...duplicateWarning(items));
    return notes.join("");
  }

  function bulkCopyMaturity(mode, value) {
    const targetIds = bulkMaturityTargetIds();
    const targets = indicatorState.items.filter((item) => targetIds.has(item.id));
    const maturityIds = new Set(
      targets
        .filter((item) => item.type === "implied_vol" || item.type === "forward")
        .map((item) => item.id),
    );
    const idMap = new Map();
    const copies = targets.map((source) => {
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
      copy.config.alias = "";
      if (maturityIds.has(source.id)) applyMaturityToItem(copy, mode, value);
      idMap.set(source.id, copy.id);
      return copy;
    });
    for (const copy of copies) {
      if (copy.type !== "derived") continue;
      for (const key of ["operandA", "operandB"]) {
        const mapped = idMap.get(Number(copy.config[key]));
        if (mapped !== undefined) copy.config[key] = mapped;
      }
    }
    indicatorState.items.push(...copies);
    const maturityCount = copies.filter(
      (copy) => copy.type === "implied_vol" || copy.type === "forward",
    ).length;
    const derivedCount = copies.filter((copy) => copy.type === "derived").length;
    const label = mode === "fixed" ? `Fixed ${value}` : `Sliding ${value}`;
    const notes = [
      `已复制 ${copies.length} 个指标，其中 ${maturityCount} 个 IV / Forward 改为 ${label}${derivedCount ? `，${derivedCount} 个运算指标已接到复制出的操作数` : ""}。`,
    ];
    notes.push(...duplicateWarning(copies));
    return notes.join("");
  }

'''
text = text[:start] + new_block + text[end:]
path.write_text(text, encoding="utf-8")

# Restore the explicit Sliding / Fixed bulk selector. Listed remains discovery-driven and is
# therefore not offered as one shared bulk target.
path = Path("app/web/index.html")
text = path.read_text(encoding="utf-8")
old = '''              <section id="bulkMaturityPanel" class="bulk-edit-panel is-hidden" aria-label="批量修改期限">
                <div class="field-grid two bulk-maturity-mode">
                  <label id="bulkSlidingMaturityField" class="field field-wide"><span>Target tenor</span><select id="bulkSlidingMaturity"></select></label>
                </div>
                <small id="bulkMaturityHelp">只支持批量改为 Sliding tenor；Spot 与 RV 没有 option tenor，不参与修改。Listed expiry 暂不支持批量修改。</small>'''
new = '''              <section id="bulkMaturityPanel" class="bulk-edit-panel is-hidden" aria-label="批量修改期限">
                <div class="field-grid two bulk-maturity-mode">
                  <label class="field"><span>期限类型</span><select id="bulkMaturityMode">
                    <option value="sliding">Sliding tenor</option>
                    <option value="fixed">Fixed date</option>
                  </select></label>
                  <label id="bulkSlidingMaturityField" class="field"><span>Target tenor</span><select id="bulkSlidingMaturity"></select></label>
                </div>
                <label id="bulkFixedMaturityField" class="field is-hidden"><span>Target date</span><input id="bulkFixedMaturity" type="date" /></label>
                <small id="bulkMaturityHelp">Sliding 与 Fixed date 都可批量修改；Fixed 按精确日期请求，可能返回 NO_DATA。Spot 与 RV 不参与；Listed expiry 暂不作为批量目标。</small>'''
text = replace_once(text, old, new, "bulk maturity HTML")
path.write_text(text, encoding="utf-8")

# Update the regression contract: fixed is allowed; only proven-invalid combinations are blocked.
path = Path("tests/integration/test_phase_d_web.py")
text = path.read_text(encoding="utf-8")
old = '''def test_bulk_maturity_only_exposes_sliding_tenor():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    panel = html.split('id="bulkMaturityPanel"', 1)[1].split("</section>", 1)[0]
    assert 'id="bulkSlidingMaturity"' in panel
    assert 'id="bulkMaturityMode"' not in panel
    assert "bulkFixedMaturity" not in panel
    assert "Fixed date" not in panel

    bulk_logic = javascript.split("function renderBulkMaturityControls", 1)[1].split(
        "function applyBulkInstrument", 1
    )[0]
    assert "bulkMaturityMode" not in bulk_logic
    assert "bulkFixedMaturity" not in bulk_logic
    assert 'item.config.maturityMode = "sliding"' in bulk_logic
    assert "Listed expiry 暂不支持批量修改" in bulk_logic'''
new = '''def test_bulk_maturity_allows_fixed_date_but_only_blocks_contract_invalid_combinations():
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/compare-builder.js").text

    panel = html.split('id="bulkMaturityPanel"', 1)[1].split("</section>", 1)[0]
    assert 'id="bulkMaturityMode"' in panel
    assert '<option value="sliding">Sliding tenor</option>' in panel
    assert '<option value="fixed">Fixed date</option>' in panel
    assert 'id="bulkFixedMaturity"' in panel
    assert "可能返回 NO_DATA" in panel

    bulk_logic = javascript.split("function renderBulkMaturityControls", 1)[1].split(
        "function applyBulkInstrument", 1
    )[0]
    assert 'mode === "fixed"' in bulk_logic
    assert "validIsoDate(value)" in bulk_logic
    assert "Delta + Sliding maturity" in bulk_logic
    assert "Absolute strike + Sliding maturity" in bulk_logic
    assert 'item.config.maturityMode = mode' in bulk_logic
    assert "坐标不存在时允许后端返回 NO_DATA" in bulk_logic
    # A source indicator being Listed is not itself an invalid target conversion. Listed is
    # simply not offered as a shared bulk target because its universe is discovered per date.
    assert "个指标使用 Listed expiry" not in bulk_logic'''
text = replace_once(text, old, new, "bulk maturity regression test")
path.write_text(text, encoding="utf-8")

# Make the product note explicit so Fixed bulk support is not mistaken for arbitrary interpolation.
path = Path("docs/phase_f_compare_indicator_builder_zh.md")
text = path.read_text(encoding="utf-8")
old = '''## 当前已知 legacy UI 边界

Bulk Maturity 仍保留 legacy `Fixed date` 入口。它不改变主 indicator builder 的当前契约，后续作为独立 cleanup 处理；在此之前不要把 Bulk 的 legacy 选项反向解释成主 UI 重新支持“任意 fixed date”。'''
new = '''## Bulk Maturity 当前语义

Bulk Maturity **有意支持** `Sliding tenor` 与 `Fixed date` 两种目标；这不改变主 indicator builder 仍以 Sliding + Listed 为普通新建入口的产品契约。

- Fixed date 是一个精确 Cortex request coordinate，不代表任意日历日期都存在数据；合法请求可正常发出，坐标不存在时由后端返回 `NO_DATA`，前端不预判、也不替换成最近期限；
- 只在组合已知违反数据契约时前端阻止，例如 `Delta IV + Fixed`、`Absolute strike IV + Sliding`；
- `Listed expiry` 不作为统一 bulk target，因为可用 expiry universe 随 underlying × observation date 变化，需要逐项 discovery；
- 一个当前使用 Listed expiry 的 source indicator，可以批量改成 Sliding 或 Fixed，只要目标组合本身合法。'''
text = replace_once(text, old, new, "Phase F bulk maturity note")
path.write_text(text, encoding="utf-8")

print("Step 6.1 patch applied")
