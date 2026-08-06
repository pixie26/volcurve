"""Sanitized Gate C/E live probe through the public FastAPI routes.

No credentials, headers, raw payloads, market values, or error bodies are
printed or written. The report contains endpoint status and structural counts.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import PROJECT_ROOT, get_settings  # noqa: E402
from app.main import app  # noqa: E402


def _arguments() -> argparse.Namespace:
    yesterday = date.today() - timedelta(days=1)
    parser = argparse.ArgumentParser(description="Run sanitized live REST API probes")
    parser.add_argument("--code", default="US_QQQ")
    parser.add_argument("--start", type=date.fromisoformat, default=yesterday - timedelta(days=10))
    parser.add_argument("--end", type=date.fromisoformat, default=yesterday)
    parser.add_argument(
        "--report",
        type=Path,
        default=(PROJECT_ROOT / "data" / "normalized" / "phase_e_validation" / "api_report.json"),
    )
    return parser.parse_args()


def _common(code: str, start: date, end: date) -> dict:
    return {"code": code, "start_date": start.isoformat(), "end_date": end.isoformat()}


def _compare_envelope(volatility_request: dict, *, force_refresh: bool = False) -> dict:
    return {
        "volatilityRequest": volatility_request,
        "rvWindowSessions": 5,
        "rvAlignment": "trailing",
        "forceRefresh": force_refresh,
    }


def _safe_result(name: str, response, *, expected: int = 200) -> dict:
    if response.status_code != expected:
        try:
            payload = response.json()
            code = payload.get("code", "UNKNOWN")
            stage = payload.get("stage", "unknown")
        except Exception:
            code, stage = "NON_JSON_ERROR", "unknown"
        print(f"{name}: FAIL HTTP_{response.status_code} {code}")
        return {
            "name": name,
            "status": "FAIL",
            "httpStatus": response.status_code,
            "errorCode": code,
            "errorStage": stage,
        }
    print(f"{name}: PASS")
    return {"name": name, "status": "PASS", "httpStatus": response.status_code}


def _surface_probe(client: TestClient, name: str, request: dict) -> tuple[dict, dict | None]:
    response = client.post(
        "/api/v1/vol/surface",
        json={"volatilityRequest": request, "forceRefresh": True},
    )
    result = _safe_result(name, response)
    if response.status_code != 200:
        return result, None
    payload = response.json()
    result.update(
        snapshotCount=payload["dataQuality"]["snapshotCount"],
        pointCount=payload["dataQuality"]["pointCount"],
        activityCodes=[event["code"] for event in payload["activity"]],
    )
    return result, payload


def _compare_probe(client: TestClient, name: str, request: dict) -> tuple[dict, dict | None]:
    response = client.post(
        "/api/v1/vol/compare", json=_compare_envelope(request, force_refresh=True)
    )
    result = _safe_result(name, response)
    if response.status_code != 200:
        return result, None
    payload = response.json()
    result.update(
        observationCount=len(payload["series"]),
        qualityStatus=payload["dataQuality"]["status"],
        activityCodes=[event["code"] for event in payload["activity"]],
    )
    return result, payload


def _fixed_from_surface(common: dict, payload: dict, *, maturity_rule: str, strike_rule: str):
    snapshot = payload["snapshots"][-1]
    maturity = snapshot["maturities"][0]
    strike = float(snapshot["strikes"][0])
    if strike_rule == "fixed":
        return {
            **common,
            "maturity_rule": maturity_rule,
            "strike_rule": "fixed",
            "low_fixed_strike": strike,
            "high_fixed_strike": strike,
            "low_fixed_maturity": maturity,
            "high_fixed_maturity": maturity,
        }
    return {
        **common,
        "maturity_rule": maturity_rule,
        "strike_rule": strike_rule,
        "low_strike": strike,
        "high_strike": strike,
        "low_fixed_maturity": maturity,
        "high_fixed_maturity": maturity,
    }


def main() -> int:
    args = _arguments()
    settings = get_settings()
    if settings.cortex_mode != "live":
        print("BLOCKED: CORTEX_MODE must be live for Gate C probes.")
        return 2
    if not settings.credentials_configured:
        print("BLOCKED: BNP credentials are not configured.")
        return 2
    if args.end < args.start:
        print("INVALID: --end must be >= --start")
        return 2

    # Do not contend with a locally running Web process for the primary DuckDB
    # file. Gate evidence is written to its own private, gitignored cache.
    validation_root = PROJECT_ROOT / "data" / "phase_e_api_runtime"
    settings.data_dir = validation_root
    settings.raw_dir = validation_root / "raw"
    settings.normalized_dir = validation_root / "normalized"
    settings.duckdb_path = validation_root / "catalog.duckdb"

    common = _common(args.code, args.start, args.end)
    ks = {
        **common,
        "maturity_rule": "sliding",
        "strike_rule": "relative_to_spot_ref",
        "low_strike": 100,
        "high_strike": 100,
        "low_maturity": "3M",
        "high_maturity": "3M",
    }
    delta = {
        **common,
        "maturity_rule": "sliding",
        "strike_rule": "delta",
        "low_delta_strike": "p25.0",
        "high_delta_strike": "p25.0",
        "low_maturity": "3M",
        "high_maturity": "3M",
    }
    fixed_surface_request = {
        **common,
        "maturity_rule": "fixed",
        "strike_rule": "fixed",
    }
    listed_surface_request = {
        **common,
        "maturity_rule": "listed",
        "strike_rule": "relative_to_forward",
        "low_strike": 100,
        "high_strike": 100,
    }

    results = []
    with TestClient(app, raise_server_exceptions=False) as client:
        instruments = client.get("/api/v1/instruments", params={"q": "QQQ"})
        instrument_result = _safe_result("instruments", instruments)
        if instruments.status_code == 200:
            instrument_result["returnedCount"] = instruments.json()["returnedCount"]
        results.append(instrument_result)

        compare_result, compare_payload = _compare_probe(client, "compare_ks", ks)
        results.append(compare_result)
        delta_result, _ = _compare_probe(client, "compare_delta", delta)
        results.append(delta_result)

        fixed_surface_result, fixed_surface = _surface_probe(
            client, "surface_fixed", fixed_surface_request
        )
        results.append(fixed_surface_result)
        if fixed_surface is not None:
            fixed_request = _fixed_from_surface(
                common, fixed_surface, maturity_rule="fixed", strike_rule="fixed"
            )
            fixed_result, _ = _compare_probe(client, "compare_fixed", fixed_request)
            results.append(fixed_result)

        listed_surface_result, listed_surface = _surface_probe(
            client, "surface_listed", listed_surface_request
        )
        results.append(listed_surface_result)
        if listed_surface is not None:
            listed_request = _fixed_from_surface(
                common,
                listed_surface,
                maturity_rule="listed",
                strike_rule="relative_to_forward",
            )
            listed_result, _ = _compare_probe(client, "compare_listed", listed_request)
            results.append(listed_result)

        csv_result = {"name": "compare_csv_consistency", "status": "FAIL"}
        if compare_payload is not None:
            csv_response = client.post("/api/v1/vol/compare.csv", json=_compare_envelope(ks))
            if csv_response.status_code == 200:
                rows = list(csv.DictReader(io.StringIO(csv_response.text)))
                json_rows = compare_payload["series"]
                consistent = len(rows) == len(json_rows) and all(
                    row["implied_vol"]
                    == ("" if point["impliedVol"] is None else str(point["impliedVol"]))
                    and row["realized_vol"]
                    == ("" if point["realizedVol"] is None else str(point["realizedVol"]))
                    for row, point in zip(rows, json_rows, strict=True)
                )
                csv_result = {
                    "name": "compare_csv_consistency",
                    "status": "PASS" if consistent else "FAIL",
                    "httpStatus": 200,
                    "rowCount": len(rows),
                    "numericConsistency": consistent,
                }
        print(f"compare_csv_consistency: {csv_result['status']}")
        results.append(csv_result)

    report = {
        "gate": "Phase E live core-mode and API/CSV validation",
        "instrumentCode": args.code,
        "requestedStart": args.start.isoformat(),
        "requestedEnd": args.end.isoformat(),
        "rawPayloadStoredInReport": False,
        "marketValuesStoredInReport": False,
        "results": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Sanitized structural report: {args.report}")
    return 0 if results and all(result["status"] == "PASS" for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
