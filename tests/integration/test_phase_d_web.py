"""Small static-contract checks for the Web shell.

Behavior belongs in tests/js and tests/browser. These tests intentionally protect only
assets and user/product contracts; they do not pretend that source strings prove runtime
behavior.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.disclosures import DISCLOSURES
from app.main import app


def _assets() -> tuple[str, dict[str, str]]:
    names = (
        "app.js",
        "compare-core.js",
        "compare-workspace.js",
        "compare-request.js",
        "compare-render.js",
        "compare-builder.js",
    )
    with TestClient(app) as client:
        html = client.get("/").text
        assets = {name: client.get(f"/static/{name}").text for name in names}
    return html, assets


def test_web_shell_and_offline_assets_are_served() -> None:
    with TestClient(app) as client:
        page = client.get("/")
        scripts = {
            name: client.get(f"/static/{name}")
            for name in (
                "app.js",
                "compare-core.js",
                "compare-workspace.js",
                "compare-request.js",
                "compare-render.js",
                "compare-builder.js",
            )
        }
        stylesheet = client.get("/static/styles.css")
        plotly = client.get("/static/vendor/plotly-5.24.1.min.js")

    html = page.text
    assert page.status_code == 200
    assert all(response.status_code == 200 for response in scripts.values())
    assert stylesheet.status_code == 200
    assert plotly.status_code == 200
    assert len(plotly.content) > 1_000_000
    assert 'lang="zh-Hans"' in html
    assert 'src="/static/vendor/plotly-5.24.1.min.js"' in html
    assert 'src="/static/compare-core.js?v=' in html
    assert 'src="/static/compare-builder.js?v=' in html
    assert html.index("/static/compare-core.js") < html.index("/static/compare-builder.js")
    assert "https://" not in html


def test_web_capability_and_disclosure_contracts_remain_exposed() -> None:
    with TestClient(app) as client:
        capabilities = client.get("/api/v1/capabilities").json()

    assert all(mode["enabled"] for mode in capabilities["requestModes"])
    assert {"smile", "term_structure"}.issubset(capabilities["indicators"])
    supported_surfaces = {
        "query_builder",
        "methodology",
        "quality_panel",
        "activity_console",
    }
    assert all(disclosure.frontendRequired for disclosure in DISCLOSURES)
    assert all(set(disclosure.frontendSurfaces) <= supported_surfaces for disclosure in DISCLOSURES)


def test_time_series_shell_exposes_current_product_controls() -> None:
    html, assets = _assets()
    workspace_js = assets["compare-workspace.js"]

    for element_id in (
        "indicatorBuilder",
        "indicatorCharts",
        "savedIndicators",
        "addChartButton",
        "bulkModeButton",
        "bulkMaturityMode",
        "bulkFixedMaturity",
        "crosshairReadout",
        "timeseriesWarning",
    ):
        assert f'id="{element_id}"' in html

    assert '<option value="sliding">Sliding tenor</option>' in html
    assert '<option value="fixed">Fixed date</option>' in html
    assert "MAX_CHARTS = 8" in workspace_js


def test_main_builder_keeps_exact_coordinate_and_wire_defaults() -> None:
    html, assets = _assets()
    app_js = assets["app.js"]
    request_js = assets["compare-request.js"]
    render_js = assets["compare-render.js"]
    workspace_js = assets["compare-workspace.js"]

    assert "Listed expiry" in render_js
    assert "Observation date" in render_js
    assert "可直接输入任意正数，也可从下拉建议选择" in render_js
    assert 'volatilityConvention: "bsVol"' in workspace_js
    assert 'layout: "matrix"' in workspace_js
    assert 'code_type: "bnpp"' in request_js
    assert "code_type" in app_js
    assert "不会自动换成邻近 strike 或 expiry" in app_js
    assert 'value="derived"' in html


def test_bulk_fixed_is_presented_as_exact_request_not_guaranteed_data() -> None:
    html, _ = _assets()

    # The exact serialized behavior is exercised in Playwright; Python only protects
    # the user-visible contract here.
    assert "Fixed 按精确日期请求，可能返回 NO_DATA" in html


def test_browser_configuration_not_market_payload_is_persisted() -> None:
    html, assets = _assets()
    workspace_js = assets["compare-workspace.js"]

    assert "行情响应不保存，重新打开后会重新请求" in html
    assert "localStorage.setItem" in workspace_js
    assert "localStorage.getItem" in workspace_js


def test_runtime_behavior_is_owned_by_executable_frontend_suites() -> None:
    """Keep the Python suite from drifting back toward source-code pseudo-tests."""

    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    assert (root / "tests/js/frontend_statistics.test.mjs").is_file()
    assert (root / "tests/js/frontend_architecture.test.mjs").is_file()
    assert (root / "tests/browser/time_series.spec.mjs").is_file()
    assert (root / "playwright.config.mjs").is_file()
