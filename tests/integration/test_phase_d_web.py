"""Gate D contracts for the offline Web MVP."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.disclosures import DISCLOSURES
from app.main import app


def test_web_workspace_and_offline_assets_are_served():
    with TestClient(app) as client:
        page = client.get("/")
        javascript = client.get("/static/app.js")
        stylesheet = client.get("/static/styles.css")
        plotly = client.get("/static/vendor/plotly-5.24.1.min.js")

    html = page.content.decode("utf-8")
    assert page.status_code == 200
    assert 'lang="zh-Hans"' in html
    assert "动态" not in html  # UI wording stays user-facing, not implementation-facing.
    assert "Compare 用于一个精确坐标" in html
    assert "未复权" in html
    assert 'src="/static/vendor/plotly-5.24.1.min.js"' in html
    assert "https://" not in html
    assert javascript.status_code == 200
    assert stylesheet.status_code == 200
    assert plotly.status_code == 200
    assert len(plotly.content) > 1_000_000


def test_web_discovers_backend_modes_and_renders_all_required_disclosure_surfaces():
    with TestClient(app) as client:
        capabilities = client.get("/api/v1/capabilities").json()
        javascript = client.get("/static/app.js").text

    assert all(mode["enabled"] for mode in capabilities["requestModes"])
    assert "state.capabilities.requestModes" in javascript
    assert "state.capabilities.moneynessLevels" in javascript
    assert "state.capabilities.deltaStrikes" in javascript
    assert {"smile", "term_structure"}.issubset(capabilities["indicators"])

    supported_surfaces = {
        "query_builder",
        "methodology",
        "quality_panel",
        "activity_console",
    }
    assert all(disclosure.frontendRequired for disclosure in DISCLOSURES)
    assert all(set(disclosure.frontendSurfaces) <= supported_surfaces for disclosure in DISCLOSURES)
    for surface in supported_surfaces:
        assert surface in javascript


def test_web_keeps_missing_coordinates_and_arbitrary_rv_windows_explicit():
    with TestClient(app) as client:
        javascript = client.get("/static/app.js").text

    assert "不会自动换成邻近 strike 或 expiry" in javascript
    assert "最近返回 strike" in javascript
    assert "最近返回 expiry" in javascript
    assert "不会自动取最近档位" in javascript
    assert "Number.isInteger(window)" in javascript
    assert "connectgaps: false" in javascript


def test_web_discovers_listed_contract_coordinates_without_auto_substitution():
    with TestClient(app) as client:
        javascript = client.get("/static/app.js").text

    assert "加载可用坐标" in javascript
    assert 'maturity_rule: "fixed"' in javascript
    assert 'strike_rule: "fixed"' in javascript
    discovery_function = javascript.split("async function loadListedCoordinates", 1)[1].split(
        "function renderAvailableStrikes", 1
    )[0]
    assert "low_fixed_strike" not in discovery_function
    assert "系统未自动选择 strike" in javascript
    assert "这是用户选择，不是最近坐标替代" in javascript
