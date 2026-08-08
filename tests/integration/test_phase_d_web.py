"""Small static-contract checks for the Web shell.

Behavior belongs in tests/js and tests/browser.  These tests intentionally avoid
asserting implementation details such as function names or source-code layout.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.disclosures import DISCLOSURES
from app.main import app


def _assets() -> tuple[str, str, str]:
    with TestClient(app) as client:
        html = client.get("/").text
        app_js = client.get("/static/app.js").text
        compare_js = client.get("/static/compare-builder.js").text
    return html, app_js, compare_js


def test_web_shell_and_offline_assets_are_served() -> None:
    with TestClient(app) as client:
        page = client.get("/")
        app_js = client.get("/static/app.js")
        compare_js = client.get("/static/compare-builder.js")
        stylesheet = client.get("/static/styles.css")
        plotly = client.get("/static/vendor/plotly-5.24.1.min.js")

    html = page.text
    assert page.status_code == 200
    assert app_js.status_code == 200
    assert compare_js.status_code == 200
    assert stylesheet.status_code == 200
    assert plotly.status_code == 200
    assert len(plotly.content) > 1_000_000
    assert 'lang="zh-Hans"' in html
    assert 'src="/static/vendor/plotly-5.24.1.min.js"' in html
    assert 'src="/static/compare-builder.js?v=' in html
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
    html, _, compare_js = _assets()

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
    assert "MAX_CHARTS = 8" in compare_js


def test_main_builder_keeps_exact_coordinate_and_wire_defaults() -> None:
    html, app_js, compare_js = _assets()

    assert "Listed expiry" in compare_js
    assert "Observation date" in compare_js
    assert "可直接输入任意正数，也可从下拉建议选择" in compare_js
    assert 'volatilityConvention: "bsVol"' in compare_js
    assert 'layout: "matrix"' in compare_js
    assert '"bnpp"' in compare_js
    assert "code_type" in app_js
    assert "不会自动换成邻近 strike 或 expiry" in app_js
    assert 'value="derived"' in html


def test_bulk_fixed_is_presented_as_exact_request_not_guaranteed_data() -> None:
    html, _, _ = _assets()

    # The exact serialized behavior is exercised in Playwright; Python only protects
    # the user-visible contract here.
    assert "Fixed 按精确日期请求，可能返回 NO_DATA" in html


def test_browser_configuration_not_market_payload_is_persisted() -> None:
    html, _, compare_js = _assets()

    assert "行情响应不保存，重新打开后会重新请求" in html
    assert "localStorage.setItem" in compare_js
    assert "localStorage.getItem" in compare_js


def test_runtime_behavior_is_owned_by_executable_frontend_suites() -> None:
    """Keep the Python suite from drifting back toward source-code pseudo-tests."""

    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    assert (root / "tests/js/frontend_statistics.test.mjs").is_file()
    assert (root / "tests/browser/time_series.spec.mjs").is_file()
    assert (root / "playwright.config.mjs").is_file()
