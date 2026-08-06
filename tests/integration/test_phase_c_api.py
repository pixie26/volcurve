"""Gate C fixture-mode integration tests for every public REST endpoint."""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_cortex_client
from app.clients.cortex.client import CortexClient
from app.clients.cortex.errors import CortexError, ErrorCode
from app.config import Settings
from app.main import app
from app.security.redaction import register_secret


@pytest.fixture
def api_client(tmp_path):
    settings = Settings()
    settings.cortex_mode = "fixture"
    settings.data_dir = tmp_path
    settings.raw_dir = tmp_path / "raw"
    settings.normalized_dir = tmp_path / "normalized"
    settings.duckdb_path = tmp_path / "catalog.duckdb"
    cortex = CortexClient(settings)
    app.dependency_overrides[get_cortex_client] = lambda: cortex
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _sliding_ks_compare() -> dict:
    return {
        "volatilityRequest": {
            "code": "US_QQQ",
            "start_date": "2020-01-02",
            "end_date": "2020-01-10",
            "maturity_rule": "sliding",
            "strike_rule": "relative_to_spot_ref",
            "low_strike": 100,
            "high_strike": 100,
            "low_maturity": "3M",
            "high_maturity": "3M",
        },
        "rvWindowSessions": 5,
        "rvAlignment": "trailing",
    }


def _surface_requests() -> list[dict]:
    common = {"code": "US_QQQ", "start_date": "2026-08-03", "end_date": "2026-08-03"}
    return [
        {
            **common,
            "maturity_rule": "sliding",
            "strike_rule": "relative_to_forward",
            "low_strike": 97.5,
            "high_strike": 100,
            "low_maturity": "1M",
            "high_maturity": "3M",
        },
        {
            **common,
            "maturity_rule": "sliding",
            "strike_rule": "delta",
            "low_delta_strike": "p25.0",
            "high_delta_strike": "c25.0",
            "low_maturity": "1M",
            "high_maturity": "3M",
        },
        {
            **common,
            "maturity_rule": "fixed",
            "strike_rule": "fixed",
            "low_fixed_strike": 600,
            "high_fixed_strike": 620,
            "low_fixed_maturity": "2026-09-18",
            "high_fixed_maturity": "2026-12-18",
        },
        {
            **common,
            "maturity_rule": "listed",
            "strike_rule": "relative_to_spot_ref",
            "low_strike": 97.5,
            "high_strike": 100,
            "low_fixed_maturity": "2026-09-18",
            "high_fixed_maturity": "2026-12-18",
        },
    ]


def _single_coordinate_compare_requests() -> list[dict]:
    surfaces = _surface_requests()
    requests = []
    for item in surfaces:
        request = dict(item)
        if request["strike_rule"] == "delta":
            request.update(
                low_delta_strike="p25.0",
                high_delta_strike="p25.0",
                low_maturity="1M",
                high_maturity="1M",
            )
        elif request["strike_rule"] == "fixed":
            request.update(
                low_fixed_strike=600,
                high_fixed_strike=600,
                low_fixed_maturity="2026-09-18",
                high_fixed_maturity="2026-09-18",
            )
        elif request["maturity_rule"] == "listed":
            request.update(
                low_strike=97.5,
                high_strike=97.5,
                low_fixed_maturity="2026-09-18",
                high_fixed_maturity="2026-09-18",
            )
        else:
            request.update(
                low_strike=97.5,
                high_strike=97.5,
                low_maturity="1M",
                high_maturity="1M",
            )
        requests.append(
            {
                "volatilityRequest": request,
                "rvWindowSessions": 5,
                "rvAlignment": "trailing",
            }
        )
    return requests


def test_fixture_mode_all_public_endpoints_and_surface_modes(api_client):
    assert api_client.get("/health/live").status_code == 200
    assert api_client.get("/api/v1/capabilities").status_code == 200

    instruments = api_client.get("/api/v1/instruments", params={"q": "QQQ"})
    assert instruments.status_code == 200
    assert instruments.json()["returnedCount"] == 3
    assert instruments.json()["activity"][-1]["code"] == "INSTRUMENTS_FILTERED"

    for volatility_request in _surface_requests():
        response = api_client.post(
            "/api/v1/vol/surface", json={"volatilityRequest": volatility_request}
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["dataQuality"]["pointCount"] == 4
        assert payload["snapshots"][0]["points"][0]["impliedVol"] > 1
        assert payload["activity"][-1]["code"] == "SURFACE_NORMALIZED"

    for compare_request in _single_coordinate_compare_requests():
        response = api_client.post("/api/v1/vol/compare", json=compare_request)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["methodology"]["volUnits"] == "percent"
        assert payload["activity"][-1]["code"] == "ANALYTICS_COMPLETED"


def test_listed_fixed_surface_can_discover_coordinates_without_bounds(api_client):
    response = api_client.post(
        "/api/v1/vol/surface",
        json={
            "volatilityRequest": {
                "code": "US_QQQ",
                "start_date": "2026-08-03",
                "end_date": "2026-08-03",
                "maturity_rule": "fixed",
                "strike_rule": "fixed",
                "layout": "matrix",
            }
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    snapshot = payload["snapshots"][0]
    assert snapshot["maturities"] == ["2026-09-18", "2026-12-18"]
    assert snapshot["strikes"] == ["600.0", "620.0"]
    assert {(point["maturity"], point["strike"]) for point in snapshot["points"]} == {
        ("2026-09-18", "600.0"),
        ("2026-09-18", "620.0"),
        ("2026-12-18", "600.0"),
        ("2026-12-18", "620.0"),
    }


def test_compare_and_csv_have_identical_values(api_client):
    body = _sliding_ks_compare()
    json_response = api_client.post("/api/v1/vol/compare", json=body)
    csv_response = api_client.post("/api/v1/vol/compare.csv", json=body)
    assert json_response.status_code == 200
    assert csv_response.status_code == 200
    assert csv_response.headers["x-activity-event"] == "CSV_GENERATED"

    json_points = json_response.json()["series"]
    csv_points = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert len(json_points) == len(csv_points)
    for json_point, csv_point in zip(json_points, csv_points, strict=True):
        assert csv_point["date"] == json_point["date"]
        for csv_name, json_name in (
            ("spot", "spot"),
            ("forward", "forward"),
            ("raw_implied_vol", "rawImpliedVol"),
            ("implied_vol", "impliedVol"),
            ("realized_vol", "realizedVol"),
            ("iv_minus_rv", "ivMinusRv"),
            ("iv_divided_by_rv", "ivDividedByRv"),
        ):
            expected = json_point[json_name]
            assert csv_point[csv_name] == ("" if expected is None else str(expected))
        assert csv_point["quality_flags"] == "|".join(json_point["qualityFlags"])


def test_compare_rejects_range_before_fetch_and_returns_normalized_error(api_client):
    body = _sliding_ks_compare()
    body["volatilityRequest"]["low_strike"] = 97.5
    response = api_client.post("/api/v1/vol/compare", json=body)
    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "INVALID_REQUEST"
    assert payload["stage"] == "validation"
    assert payload["requestId"] == response.headers["x-request-id"]
    assert "traceback" not in response.text.casefold()


def test_validation_and_upstream_errors_do_not_leak_secrets_or_paths(api_client):
    secret = "SYNTHETIC_PHASE_C_SECRET"
    register_secret(secret)
    invalid = _sliding_ks_compare()
    invalid["volatilityRequest"]["low_strike"] = secret
    validation = api_client.post("/api/v1/vol/compare", json=invalid)
    assert validation.status_code == 422
    assert secret not in validation.text

    class FailingClient:
        def get_instruments_with_result(self, _instrument_type):
            raise CortexError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                f"Bearer abc.def {secret} D:\\private\\raw.json",
            )

    app.dependency_overrides[get_cortex_client] = lambda: FailingClient()
    failure = api_client.get("/api/v1/instruments", params={"q": "QQQ"})
    assert failure.status_code == 502
    assert secret not in failure.text
    assert "abc.def" not in failure.text
    assert "D:\\private" not in failure.text
    assert "[REDACTED]" in failure.text
