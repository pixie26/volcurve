"""Gate 0 probe: authentication, reachability, entitlement.

Prints only PASS/FAIL and non-sensitive metadata. Never prints tokens,
secrets, or Authorization headers.

Usage: python scripts/auth_probe.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.clients.cortex.auth import AuthenticationManager  # noqa: E402
from app.clients.cortex.errors import CortexError  # noqa: E402
from app.config import get_settings  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    settings = get_settings()

    # --- credentials present (not printed) ---
    check("凭证已配置 (.env)", settings.credentials_configured)
    if not settings.credentials_configured:
        return summarize(1)

    auth = AuthenticationManager(settings)

    # --- token acquisition ---
    token = None
    try:
        token = auth.get_token()
        check("Bearer token 获取成功", bool(token))
    except CortexError as exc:
        check("Bearer token 获取成功", False, f"{exc.code.value} (status={exc.status})")
        return summarize(1)

    # --- expiry parsed ---
    expiry = auth.token_expiry()
    ttl = (expiry - time.time()) if expiry else None
    check(
        "Token expiry 已正确解析",
        ttl is not None and ttl > 0,
        f"有效期约 {int(ttl)} 秒" if ttl else "",
    )

    # --- production base URL reachable + entitlement via /v1/instruments ---
    instruments_count = None
    try:
        with httpx.Client(
            verify=settings.bnp_verify_tls,
            proxy=settings.http_proxy,
            timeout=60.0,
        ) as client:
            resp = client.get(
                f"{settings.bnp_base_url}/v1/instruments",
                params={"type": "equity"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
        if resp.status_code == 200:
            data = resp.json()
            instruments_count = len(data) if isinstance(data, list) else None
            check("Production base URL 可访问", True, settings.bnp_base_url)
            check(
                "/v1/instruments 请求成功",
                True,
                f"equity instruments 数量: {instruments_count}",
            )
            check("Client entitlement 已确认", True, "数据接口返回 200")
        elif resp.status_code == 403:
            check("Production base URL 可访问", True)
            check(
                "Client entitlement 已确认",
                False,
                "403 — 凭证未开通 Cortex DataHub 数据权限,需联系 BNP 开通",
            )
        else:
            check("/v1/instruments 请求成功", False, f"status={resp.status_code}")
    except httpx.HTTPError as exc:
        check("Production base URL 可访问", False, type(exc).__name__)

    # --- API version confirmed from archived spec ---
    spec = Path(__file__).resolve().parent.parent / "schemas" / "cortex-openapi.yaml"
    version = None
    if spec.exists():
        for line in spec.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("version:"):
                version = line.split(":", 1)[1].strip()
                break
    check("BNP API version 已确认", version is not None, f"归档 OAS version={version}")

    # --- secret hygiene (filesystem level; git not required here) ---
    gitignore = Path(__file__).resolve().parent.parent / ".gitignore"
    ignored = gitignore.exists() and ".env" in gitignore.read_text(encoding="utf-8")
    check(".env 已被 .gitignore 排除", ignored)

    return summarize(0 if all(ok for _, ok, _ in RESULTS) else 1)


def summarize(code: int) -> int:
    failed = [n for n, ok, _ in RESULTS if not ok]
    print()
    if failed:
        print(f"Gate 0 未通过,失败项: {', '.join(failed)}")
    else:
        print("Gate 0 全部通过")
    return code


if __name__ == "__main__":
    sys.exit(main())
