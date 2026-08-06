from __future__ import annotations

import os

from app.config import _load_local_env


def test_load_local_env_accepts_utf8_bom(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "BNP_CLIENT_ID=test-client\nBNP_CLIENT_SECRET=test-secret\n",
        encoding="utf-8-sig",
    )
    monkeypatch.delenv("BNP_CLIENT_ID", raising=False)
    monkeypatch.delenv("BNP_CLIENT_SECRET", raising=False)

    assert _load_local_env(env_path)
    assert os.environ["BNP_CLIENT_ID"] == "test-client"
    assert os.environ["BNP_CLIENT_SECRET"] == "test-secret"
