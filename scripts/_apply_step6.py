from pathlib import Path

def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")

replace_once(
    "app/web/index.html",
    '''              <section id="bulkMaturityPanel" class="bulk-edit-panel is-hidden" aria-label="批量修改期限">
                <div class="field-grid two bulk-maturity-mode">
                  <label class="field"><span>期限类型</span><select id="bulkMaturityMode">
                    <option value="sliding">Sliding tenor</option>
                    <option value="fixed">Fixed date</option>
                  </select></label>
                  <label id="bulkSlidingMaturityField" class="field"><span>Target tenor</span><select id="bulkSlidingMaturity"></select></label>
                </div>
                <label id="bulkFixedMaturityField" class="field is-hidden"><span>Target date</span><input id="bulkFixedMaturity" type="date" /></label>
                <small id="bulkMaturityHelp">只修改 IV / Forward 的 maturity；Spot 与 RV 没有 option tenor，不参与修改。Listed expiry 暂不支持批量修改。</small>
''',
    '''              <section id="bulkMaturityPanel" class="bulk-edit-panel is-hidden" aria-label="批量修改期限">
                <div class="field-grid two bulk-maturity-mode">
                  <label id="bulkSlidingMaturityField" class="field field-wide"><span>Target tenor</span><select id="bulkSlidingMaturity"></select></label>
                </div>
                <small id="bulkMaturityHelp">只支持批量改为 Sliding tenor；Spot 与 RV 没有 option tenor，不参与修改。Listed expiry 暂不支持批量修改。</small>
''',
    "bulk maturity HTML",
)

replace_once(
    "app/web/compare-builder.js",
    '''    on("bulkMaturityTab", "click", () => setBulkEditMode("maturity"));
    on("bulkMaturityMode", "change", renderBulkMaturityControls);
    on("bulkSlidingMaturity", "change", syncBulkMaturityButtons);
    on("bulkFixedMaturity", "change", syncBulkMaturityButtons);
    on("bulkMaturityMoveButton", "click", () => applyBulkMaturity({ copy: false }));
''',
    '''    on("bulkMaturityTab", "click", () => setBulkEditMode("maturity"));
    on("bulkSlidingMaturity", "change", syncBulkMaturityButtons);
    on("bulkMaturityMoveButton", "click", () => applyBulkMaturity({ copy: false }));
''',
    "bulk maturity bindings",
)

old_render = '''  function renderBulkMaturityControls() {
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
      help.textContent = `将修改 ${items.length} 个 IV / Forward。Sliding 与 Fixed date 支持批量；Listed expiry 暂不支持。${suffix}`;
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
    const listed = items.filter((item) => item.config.maturityMode === "listed");
    if (listed.length) {
      return `有 ${listed.length} 个指标使用 Listed expiry；Listed 暂不支持批量修改期限，请先单独编辑。`;
    }
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
    const notes = [`已把 ${items.length} 个 IV / Forward 换成 ${value}。`];
    if (renamed) notes.push(`其中 ${renamed} 个保留了原有别名，如不再合适请双击列头改名。`);
    notes.push(...duplicateWarning(items));
    return notes.join("");
  }

  function bulkCopyMaturity(mode, value) {
'''
new_render = '''  function renderBulkMaturityControls() {
    const items = bulkMaturityItems();
    const select = $("bulkSlidingMaturity");
    if (select) {
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
      help.textContent = `将修改 ${items.length} 个 IV / Forward；只支持批量改为 Sliding tenor，Listed expiry 暂不支持批量修改。${suffix}`;
    }
    syncBulkMaturityButtons();
  }

  function syncBulkMaturityButtons() {
    const items = bulkMaturityItems();
    const value = $("bulkSlidingMaturity")?.value || "";
    const enabled = items.length > 0 && Boolean(value);
    if ($("bulkMaturityMoveButton")) $("bulkMaturityMoveButton").disabled = !enabled;
    if ($("bulkMaturityCopyButton")) $("bulkMaturityCopyButton").disabled = !enabled;
  }

  function bulkMaturityCompatibility(items, value) {
    if (!items.length) return "所选项里没有 IV 或 Forward 可以修改期限。";
    const listed = items.filter((item) => item.config.maturityMode === "listed");
    if (listed.length) {
      return `有 ${listed.length} 个指标使用 Listed expiry；Listed 暂不支持批量修改期限，请先单独编辑。`;
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

  function applyMaturityToItem(item, value) {
    item.config.maturityMode = "sliding";
    item.config.slidingMaturity = value;
    item.config.expiry = "";
    item.status = initialStatus(item.type);
    item.response = null;
    item.request = null;
    item.error = null;
  }

  function applyBulkMaturity({ copy }) {
    hideIndicatorFormError();
    const value = $("bulkSlidingMaturity")?.value || "";
    const items = bulkMaturityItems();
    const problem = bulkMaturityCompatibility(items, value);
    if (problem) return setBulkNote(problem, "is-error");

    const outcome = copy
      ? bulkCopyMaturity(value)
      : bulkMoveMaturity(items, value);
    persistWorkspace();
    refreshWorkspacePanels();
    fetchMissingDependencies();
    renderBulkMaturityControls();
    setBulkNote(outcome);
  }

  function bulkMoveMaturity(items, value) {
    const renamed = items.filter((item) => indicatorAlias(item)).length;
    for (const item of items) applyMaturityToItem(item, value);
    const notes = [`已把 ${items.length} 个 IV / Forward 换成 Sliding ${value}。`];
    if (renamed) notes.push(`其中 ${renamed} 个保留了原有别名，如不再合适请双击列头改名。`);
    notes.push(...duplicateWarning(items));
    return notes.join("");
  }

  function bulkCopyMaturity(value) {
'''
replace_once("app/web/compare-builder.js", old_render, new_render, "bulk maturity logic")

replace_once(
    "app/web/compare-builder.js",
    '''      if (maturityIds.has(source.id)) applyMaturityToItem(copy, mode, value);
''',
    '''      if (maturityIds.has(source.id)) applyMaturityToItem(copy, value);
''',
    "bulk maturity copy apply",
)

replace_once(
    "app/clients/cortex/client.py",
    '''        logger.warning(
            "cortex upstream %s cid=%s body=%s",
            status,
            correlation_id,
            redact(response.text[:300]),
        )
''',
    '''        logger.warning(
            "cortex upstream status=%s cid=%s code=%r message=%r",
            status,
            correlation_id,
            upstream_code,
            upstream_message,
        )
''',
    "upstream error log",
)

p = Path("tests/unit/test_http_retry.py")
text = p.read_text(encoding="utf-8")
if "import logging\n" not in text:
    text = text.replace("from email.utils import format_datetime\n", "from email.utils import format_datetime\nimport logging\n", 1)
marker = '''def test_upstream_non_json_error_uses_normalized_error_without_upstream_fields():
'''
test = '''def test_upstream_error_log_never_records_unwhitelisted_response_body(caplog):
    client = object.__new__(CortexClient)
    response = httpx.Response(
        400,
        json={
            "code": "BNP_BAD_COORDINATE",
            "message": "Requested coordinate is unavailable.",
            "suggestedAction": "Try another coordinate.",
            "secretField": "RAW_BODY_SECRET_MARKER",
        },
    )

    with caplog.at_level(logging.WARNING, logger="cortex.client"):
        with pytest.raises(CortexError):
            client._handle_response(response, "log-boundary")

    log_text = caplog.text
    assert "BNP_BAD_COORDINATE" in log_text
    assert "Requested coordinate is unavailable." in log_text
    assert "RAW_BODY_SECRET_MARKER" not in log_text
    assert "secretField" not in log_text
    assert "suggestedAction" not in log_text


'''
if test not in text:
    if marker not in text:
        raise SystemExit("http retry insertion marker missing")
    text = text.replace(marker, test + marker, 1)
p.write_text(text, encoding="utf-8")

p = Path("tests/integration/test_phase_d_web.py")
text = p.read_text(encoding="utf-8")
test = '''\n\ndef test_bulk_maturity_only_exposes_sliding_tenor():
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
    assert "Listed expiry 暂不支持批量修改" in bulk_logic
'''
if "def test_bulk_maturity_only_exposes_sliding_tenor():" not in text:
    text += test
p.write_text(text, encoding="utf-8")

replace_once(
    "docs/operations_runbook_zh.md",
    '''- GitHub 仓库当前为 public；安全边界**不得依赖 repository visibility**。`.env`、token、licensed raw response、内部部署 secret 或未脱敏行情样本不得提交 Git。若未来需要把上述内部材料纳入仓库，应先把仓库改为 private/restricted。
''',
    '''- GitHub 仓库当前为 public；安全边界**不得依赖 repository visibility**。`.env`、token、licensed raw response、内部部署 secret 或未脱敏行情样本不得提交 Git。
- **Release TODO：项目完善并进入正式团队交付前，将 GitHub repository 切换为 private。** 这是一项明确的发布清单要求，不替代 secret/raw-data 的独立安全边界。
''',
    "private repo release reminder",
)

print("Step 6 patch applied.")
