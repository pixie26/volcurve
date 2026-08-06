"""OAuth2 client-credentials authentication manager for BNP Cortex DataHub.

Guarantees:
- token cached in memory only, refreshed 60s before expiry;
- a lock prevents concurrent refresh storms;
- the token is never written to disk or logs;
- failure modes are classified into the normalized error taxonomy.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import httpx

from app.clients.cortex.errors import CortexError, ErrorCode
from app.config import Settings

_REFRESH_MARGIN_SECONDS = 60
_TOKEN_TIMEOUT_SECONDS = 30.0


@dataclass
class _Token:
    value: str
    expires_at: float  # epoch seconds


class AuthenticationManager:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = threading.Lock()
        self._token: _Token | None = None

    def get_token(self) -> str:
        """Return a valid bearer token, refreshing when needed."""
        with self._lock:
            if self._token is None or self._expiring_soon(self._token):
                self._token = self._request_token()
            return self._token.value

    def invalidate(self) -> None:
        """Force a refresh on next use (e.g. after a 401)."""
        with self._lock:
            self._token = None

    def token_expiry(self) -> float | None:
        with self._lock:
            return self._token.expires_at if self._token else None

    @staticmethod
    def _expiring_soon(token: _Token) -> bool:
        return time.time() >= token.expires_at - _REFRESH_MARGIN_SECONDS

    def _request_token(self) -> _Token:
        self._settings.require_credentials()
        try:
            with httpx.Client(
                verify=self._settings.bnp_verify_tls,
                proxy=self._settings.http_proxy,
                timeout=_TOKEN_TIMEOUT_SECONDS,
            ) as client:
                response = client.post(
                    self._settings.bnp_token_url,
                    auth=(self._settings.bnp_client_id, self._settings.bnp_client_secret),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={"grant_type": "client_credentials"},
                )
        except httpx.TimeoutException as exc:
            raise CortexError(
                ErrorCode.UPSTREAM_UNAVAILABLE, "认证服务连接超时", status=None
            ) from exc
        except httpx.HTTPError as exc:
            raise CortexError(
                ErrorCode.UPSTREAM_UNAVAILABLE, "认证服务连接失败", status=None
            ) from exc

        if response.status_code in (400, 401):
            raise CortexError(
                ErrorCode.AUTHENTICATION_FAILED,
                "客户端凭证被拒绝,请核对 clientId/clientSecret",
                status=response.status_code,
            )
        if response.status_code == 403:
            raise CortexError(
                ErrorCode.ENTITLEMENT_DENIED,
                "凭证无权访问认证服务(403)",
                status=response.status_code,
            )
        if response.status_code == 429:
            raise CortexError(ErrorCode.UPSTREAM_RATE_LIMITED, "认证服务限流", status=429)
        if response.status_code >= 500:
            raise CortexError(
                ErrorCode.UPSTREAM_UNAVAILABLE, "认证服务暂时不可用", status=response.status_code
            )
        if response.status_code != 200:
            raise CortexError(
                ErrorCode.AUTHENTICATION_FAILED,
                f"认证服务返回非预期状态 {response.status_code}",
                status=response.status_code,
            )

        try:
            payload = response.json()
            access_token = payload["access_token"]
            expires_in = int(payload["expires_in"])
        except (ValueError, KeyError, TypeError) as exc:
            raise CortexError(
                ErrorCode.SCHEMA_CHANGED, "认证响应格式异常", status=response.status_code
            ) from exc

        return _Token(value=access_token, expires_at=time.time() + expires_in)
