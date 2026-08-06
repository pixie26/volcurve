"""Cortex DataHub client.

Responsibilities:
- HTTP stability: connect/read timeouts, 429 Retry-After, 5xx exponential
  backoff, bounded retries, per-request correlation ID;
- no retry on 400 / 403 / schema-invalid; 401 triggers one token refresh
  and one retry;
- persistent cache: raw store (authoritative) + DuckDB catalog index;
  historical ranges are permanent, intraday ranges have a short TTL;
- fixture mode (CORTEX_MODE=fixture): serve sanitized fixtures instead of
  calling BNP, so the app and tests run offline.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from app.clients.cortex.auth import AuthenticationManager
from app.clients.cortex.errors import CortexError, ErrorCode
from app.clients.cortex.parser import parse_surface
from app.config import Settings
from app.domain.instruments import Instrument
from app.domain.observations import StandardObservation
from app.domain.requests import ImpliedVolRequest
from app.security.redaction import redact, register_secret
from app.storage import cache as cache_policy_mod
from app.storage.catalog import Catalog
from app.storage.normalized_store import NormalizedStore
from app.storage.raw_store import RawStore

logger = logging.getLogger("cortex.client")

_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 120.0
_MAX_RETRIES = 4
_BACKOFF_BASE = 0.5
_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


@dataclass
class FetchResult:
    payload: list
    cache_status: str  # "live" | "hit" | "fixture"
    correlation_id: str
    retrieved_at: datetime


def load_api_version(project_root: Path) -> str:
    spec = project_root / "schemas" / "cortex-openapi.yaml"
    if spec.exists():
        for line in spec.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("version:"):
                return line.split(":", 1)[1].strip()
    return "1.60.0"


class CortexClient:
    def __init__(
        self,
        settings: Settings,
        auth: AuthenticationManager | None = None,
        catalog: Catalog | None = None,
        raw_store: RawStore | None = None,
        normalized_store: NormalizedStore | None = None,
    ):
        self._settings = settings
        self._mode = settings.cortex_mode
        self._auth = auth or AuthenticationManager(settings)
        self._catalog = catalog or Catalog(settings.duckdb_path)
        self._raw = raw_store or RawStore(settings.raw_dir)
        self._normalized = normalized_store or NormalizedStore(settings.normalized_dir)
        from app.config import PROJECT_ROOT

        self.api_version = load_api_version(PROJECT_ROOT)
        register_secret(settings.bnp_client_id)
        register_secret(settings.bnp_client_secret)

    # ------------------------------------------------------------------ public

    def get_instruments(self, instrument_type: str = "equity") -> list[Instrument]:
        if self._mode == "fixture":
            data = self._load_fixture("instruments_equity.json")
        else:
            endpoint = "instruments"
            request_hash = f"instruments_{instrument_type}_{self.api_version}"
            cached = self._try_cache(endpoint, request_hash)
            if cached is not None:
                data = cached.payload
            else:
                data = self._request_with_retry(
                    "GET",
                    "/v1/instruments",
                    params={"type": instrument_type},
                    correlation_id=request_hash,
                )
                self._persist(endpoint, request_hash, data, "intraday", instrument_type)
                self._normalized.save_instruments(data)
        return [Instrument.model_validate(item) for item in data]

    def get_implied_volatility(
        self, request: ImpliedVolRequest, *, force_refresh: bool = False
    ) -> tuple[list[StandardObservation], FetchResult]:
        request_hash = request.request_hash(self.api_version)
        if self._mode == "fixture":
            payload = self._load_fixture("implied_vol_surface.json")
            result = FetchResult(payload, "fixture", "fixture", datetime.now())
        else:
            result = None
            if not force_refresh:
                result = self._try_cache("implied-volatility", request_hash)
            if result is None:
                correlation_id = uuid.uuid4().hex[:12]
                payload = self._request_with_retry(
                    "POST",
                    "/v1/implied-volatility",
                    json_body=request.to_api_body(),
                    correlation_id=correlation_id,
                )
                self._persist(
                    "implied-volatility",
                    request_hash,
                    payload,
                    cache_policy_mod.cache_policy(request.end_date),
                    request.code,
                    start_end=(request.start_date, request.end_date),
                    request_json=json.dumps(request.to_api_body(), sort_keys=True),
                    correlation_id=correlation_id,
                )
                result = FetchResult(payload, "live", correlation_id, datetime.now())

        observations = parse_surface(result.payload, request)
        self._normalized.save_implied_vol(request_hash, observations)
        quality = "OK" if all(
            len(o.quality_flags) == 1 and o.quality_flags[0].value == "OK" for o in observations
        ) else "WARNINGS"
        self._catalog.upsert(
            request_hash=request_hash,
            endpoint="implied-volatility",
            api_version=self.api_version,
            instrument=request.code,
            start_date=request.start_date,
            end_date=request.end_date,
            request_json=json.dumps(request.to_api_body(), sort_keys=True),
            response_hash=RawStore.payload_hash(result.payload),
            retrieved_at=result.retrieved_at,
            status="completed",
            cache_policy=cache_policy_mod.cache_policy(request.end_date),
            correlation_id=result.correlation_id,
            quality_status=quality,
        )
        return observations, result

    def get_curves(self, *_args, **_kwargs):
        """Skeleton only — not part of the phase-1 UI (plan section 8.1)."""
        raise NotImplementedError("get_curves 不在第一阶段页面范围")

    # ----------------------------------------------------------------- cache

    def _try_cache(self, endpoint: str, request_hash: str) -> FetchResult | None:
        entry = self._catalog.get(request_hash)
        if entry is None or entry["status"] != "completed":
            return None
        if not cache_policy_mod.is_fresh(entry["retrieved_at"], entry["cache_policy"]):
            return None
        payload = self._raw.load(endpoint, request_hash)
        if payload is None:
            return None
        return FetchResult(payload, "hit", entry["correlation_id"], entry["retrieved_at"])

    def _persist(
        self,
        endpoint: str,
        request_hash: str,
        payload: object,
        policy: str,
        instrument: str | None,
        start_end: tuple | None = None,
        request_json: str = "",
        correlation_id: str = "",
    ) -> None:
        self._raw.save(endpoint, request_hash, payload)
        self._catalog.upsert(
            request_hash=request_hash,
            endpoint=endpoint,
            api_version=self.api_version,
            instrument=instrument,
            start_date=start_end[0] if start_end else None,
            end_date=start_end[1] if start_end else None,
            request_json=request_json,
            response_hash=RawStore.payload_hash(payload),
            retrieved_at=datetime.now(),
            status="completed",
            cache_policy=policy,
            correlation_id=correlation_id,
            quality_status="UNKNOWN",
        )

    # ------------------------------------------------------------------ http

    def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        correlation_id: str,
    ) -> list:
        attempt = 0
        refreshed_once = False
        last_error: CortexError | None = None

        while attempt <= _MAX_RETRIES:
            attempt += 1
            try:
                return self._single_request(
                    method, path, params=params, json_body=json_body, correlation_id=correlation_id
                )
            except CortexError as exc:
                last_error = exc
                if exc.code == ErrorCode.AUTHENTICATION_FAILED and not refreshed_once:
                    refreshed_once = True
                    self._auth.invalidate()
                    continue
                if exc.code == ErrorCode.UPSTREAM_RATE_LIMITED and attempt <= _MAX_RETRIES:
                    time.sleep(self._retry_after(exc) or self._backoff(attempt))
                    continue
                if exc.code == ErrorCode.UPSTREAM_UNAVAILABLE and attempt <= _MAX_RETRIES:
                    time.sleep(self._backoff(attempt))
                    continue
                raise
        raise last_error or CortexError(ErrorCode.UPSTREAM_UNAVAILABLE, "上游调用失败")

    def _single_request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None,
        json_body: dict | None,
        correlation_id: str,
    ) -> list:
        token = self._auth.get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-Correlation-ID": correlation_id,
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        url = f"{self._settings.bnp_base_url}{path}"
        timeout = httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
        try:
            with httpx.Client(
                verify=self._settings.bnp_verify_tls,
                proxy=self._settings.http_proxy,
                timeout=timeout,
            ) as client:
                response = client.request(
                    method, url, params=params, json=json_body, headers=headers
                )
        except httpx.TimeoutException as exc:
            logger.warning("cortex timeout cid=%s", correlation_id)
            raise CortexError(ErrorCode.UPSTREAM_UNAVAILABLE, "上游请求超时") from exc
        except httpx.HTTPError as exc:
            logger.warning("cortex http error cid=%s: %s", correlation_id, redact(str(exc)))
            raise CortexError(ErrorCode.UPSTREAM_UNAVAILABLE, "上游连接失败") from exc

        return self._handle_response(response, correlation_id)

    def _handle_response(self, response: httpx.Response, correlation_id: str) -> list:
        status = response.status_code
        if status == 200:
            try:
                data = response.json()
            except ValueError as exc:
                raise CortexError(ErrorCode.SCHEMA_CHANGED, "响应不是合法 JSON", status=status) from exc
            if not isinstance(data, list):
                raise CortexError(ErrorCode.SCHEMA_CHANGED, "响应顶层不是数组", status=status)
            return data

        logger.warning(
            "cortex upstream %s cid=%s body=%s",
            status, correlation_id, redact(response.text[:300]),
        )
        if status == 400:
            raise CortexError(ErrorCode.INVALID_REQUEST, "上游拒绝请求参数(400)", status=status)
        if status == 401:
            raise CortexError(ErrorCode.AUTHENTICATION_FAILED, "token 失效(401)", status=status)
        if status == 403:
            raise CortexError(
                ErrorCode.ENTITLEMENT_DENIED, "无该数据访问权限(403)", status=status
            )
        if status == 404:
            raise CortexError(ErrorCode.NO_DATA, "上游无此数据(404)", status=status)
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            exc = CortexError(ErrorCode.UPSTREAM_RATE_LIMITED, "上游限流(429)", status=status)
            exc.retry_after = float(retry_after) if retry_after else None
            raise exc
        if status >= 500:
            raise CortexError(
                ErrorCode.UPSTREAM_UNAVAILABLE, f"上游服务异常({status})", status=status
            )
        raise CortexError(ErrorCode.UPSTREAM_UNAVAILABLE, f"上游返回非预期状态({status})", status=status)

    # ----------------------------------------------------------------- misc

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(_BACKOFF_BASE * (2 ** (attempt - 1)), 30.0)

    @staticmethod
    def _retry_after(exc: CortexError) -> float | None:
        return getattr(exc, "retry_after", None)

    @staticmethod
    def _load_fixture(name: str):
        path = _FIXTURE_DIR / name
        if not path.exists():
            raise CortexError(ErrorCode.CONFIGURATION_ERROR, f"fixture 缺失: {name}")
        return json.loads(path.read_text(encoding="utf-8"))
