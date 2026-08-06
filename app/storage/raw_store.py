"""Raw response store: the authoritative source of truth.

Every successful upstream response is persisted verbatim (gzip JSON) at
data/raw/{endpoint}/{request_hash}.json.gz. Normalized stores and the
DuckDB catalog are derivable from these files and can be rebuilt.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path


class RawStore:
    def __init__(self, raw_dir: Path):
        self._raw_dir = raw_dir

    def _path(self, endpoint: str, request_hash: str) -> Path:
        return self._raw_dir / endpoint / f"{request_hash}.json.gz"

    def save(self, endpoint: str, request_hash: str, payload: object) -> Path:
        path = self._path(endpoint, request_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        with gzip.open(path, "wb") as fh:
            fh.write(blob)
        return path

    def load(self, endpoint: str, request_hash: str) -> object | None:
        path = self._path(endpoint, request_hash)
        if not path.exists():
            return None
        with gzip.open(path, "rb") as fh:
            return json.loads(fh.read().decode("utf-8"))

    def exists(self, endpoint: str, request_hash: str) -> bool:
        return self._path(endpoint, request_hash).exists()

    @staticmethod
    def payload_hash(payload: object) -> str:
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()
