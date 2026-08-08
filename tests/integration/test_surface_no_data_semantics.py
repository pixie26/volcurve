"""Regression tests for source-independent empty-surface semantics."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.deps import get_cortex_client
from app.clients.cortex.client import FetchResult
from app.main import app


class EmptyCoveringCacheClient:
    """Mimic a wider cached response cropped down to zero requested observations."""

    def get_implied_volatility_surface(self, _request, *, force_refresh=False):
        del force_refresh
        return [], FetchResult(
            payload=[],
            cache_status="cache",
            correlation_id="covering-cache",
            retrieved_at=datetime.now(UTC),
        )


def test_empty_covering_cache_surface_returns_no_data_not_200_empty_payload():
    app.dependency_overrides[get_cortex_client] = lambda: EmptyCoveringCacheClient()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/v1/vol/surface",
                json={
                    "volatilityRequest": {
                        "code": "US_QQQ",
                        "start_date": "2026-08-08",
                        "end_date": "2026-08-08",
                        "maturity_rule": "sliding",
                        "strike_rule": "relative_to_forward",
                        "low_strike": 100,
                        "high_strike": 100,
                        "low_maturity": "3M",
                        "high_maturity": "3M",
                    }
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    payload = response.json()
    assert payload["code"] == "NO_DATA"
    assert payload["stage"] == "fetch"
    assert payload["requestId"] == response.headers["x-request-id"]
    assert "snapshots" not in payload
