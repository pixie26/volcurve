import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import connectivity_status, mark_connectivity
from app.domain.api_requests import CompareApiRequest
from app.main import app


def test_capabilities_exposes_all_gate_b_verified_modes():
    response = TestClient(app).get("/api/v1/capabilities")
    assert response.status_code == 200
    payload = response.json()
    enabled = [mode["id"] for mode in payload["requestModes"] if mode["enabled"]]
    assert enabled == [
        "sliding_moneyness",
        "sliding_delta",
        "fixed_strike",
        "listed_moneyness",
    ]
    assert payload["priceAdjustment"] == "unadjusted"
    assert "implied_vol" in payload["indicators"]
    assert 97.5 in payload["moneynessLevels"]
    assert payload["instrumentSearch"]["types"] == ["equity"]
    assert payload["instrumentSearch"]["maximumMaxResults"] == 200
    assert payload["endpoints"]["compareCsv"] == "/api/v1/vol/compare.csv"
    assert payload["rvWindows"] == [5, 10, 20, 40, 60, 90, 120, 250, 500]
    assert payload["rvWindowRange"] == {
        "minimum": 2,
        "maximum": None,
        "integerOnly": True,
        "nearestSubstitution": False,
    }
    disclosure_ids = {item["id"] for item in payload["disclosures"]}
    assert "invalid_iv_exclusion" in disclosure_ids
    assert "forward_rv_fetch_extension" in disclosure_ids
    assert "large_surface_not_truncated" in disclosure_ids
    assert "instrument_catalog_scope" in disclosure_ids
    assert all(item["frontendSurfaces"] for item in payload["disclosures"])
    assert all(item["frontendRequired"] is True for item in payload["disclosures"])
    assert all(mode["enabled"] is mode["evidence"]["liveProbe"] for mode in payload["requestModes"])


def _compare_request_with_window(window):
    return {
        "volatilityRequest": {
            "code": "US_QQQ",
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
            "maturity_rule": "sliding",
            "strike_rule": "relative_to_spot_ref",
            "low_strike": 100,
            "high_strike": 100,
            "low_maturity": "3M",
            "high_maturity": "3M",
        },
        "rvWindowSessions": window,
    }


def test_rv_window_accepts_custom_integer_without_nearest_substitution():
    request = CompareApiRequest.model_validate(_compare_request_with_window(22))
    assert request.rvWindowSessions == 22
    large_request = CompareApiRequest.model_validate(_compare_request_with_window(100_000))
    assert large_request.rvWindowSessions == 100_000


@pytest.mark.parametrize("window", [0, 1, -5, 22.5, "22", True])
def test_rv_window_rejects_mathematically_invalid_or_non_integer_values(window):
    with pytest.raises(ValidationError):
        CompareApiRequest.model_validate(_compare_request_with_window(window))


def test_health_live_is_side_effect_free():
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_connectivity_beacon_preserves_explicit_failure_state():
    mark_connectivity(False)
    failed = connectivity_status()
    assert failed["connected"] is False
    assert failed["since"] is not None

    mark_connectivity(True)
    assert connectivity_status()["connected"] is True
