"""Application configuration loaded from environment / local .env.

python-dotenv is used for local development only; in deployment the same
variables are expected to be provided by the environment.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env")


class ConfigError(RuntimeError):
    pass


class Settings:
    def __init__(self) -> None:
        self.bnp_client_id = os.getenv("BNP_CLIENT_ID", "").strip()
        self.bnp_client_secret = os.getenv("BNP_CLIENT_SECRET", "").strip()
        self.bnp_token_url = os.getenv(
            "BNP_TOKEN_URL", "https://api.cib.bnpparibas.com/oauth2/v1/token"
        ).strip()
        self.bnp_base_url = os.getenv(
            "BNP_BASE_URL", "https://api.cib.bnpparibas.com/gm-cortex-datahub"
        ).strip().rstrip("/")
        # live = call BNP; fixture = offline mode backed by tests/fixtures
        self.cortex_mode = os.getenv("CORTEX_MODE", "live").strip().lower()
        # Official samples disable TLS verification for proxied corporate
        # environments; keep verification ON by default.
        self.bnp_verify_tls = os.getenv("BNP_VERIFY_TLS", "true").strip().lower() != "false"
        self.http_proxy = os.getenv("BNP_HTTP_PROXY", "").strip() or None

        self.data_dir = DATA_DIR
        self.raw_dir = DATA_DIR / "raw"
        self.normalized_dir = DATA_DIR / "normalized"
        self.duckdb_path = DATA_DIR / "catalog.duckdb"

    @property
    def credentials_configured(self) -> bool:
        return bool(self.bnp_client_id and self.bnp_client_secret)

    def require_credentials(self) -> None:
        if not self.credentials_configured:
            raise ConfigError(
                "BNP_CLIENT_ID/BNP_CLIENT_SECRET 未配置,请在 .env 中填写后重试"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
