"""Verified raw request-cache store.

Every successful upstream response is first persisted verbatim (gzip JSON) at
``data/raw/{endpoint}/{request_hash}.json.gz``.  These files remain the authority for
an individual cached request while they are retained.  Step 7 may later compact expired
request files after an eligible exact series has been committed to the revision-aware
historical point library; therefore ``data/raw`` is no longer the permanent archive.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
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
        fd, temp_name = tempfile.mkstemp(prefix=f".{request_hash}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as raw_fh:
                with gzip.GzipFile(fileobj=raw_fh, mode="wb") as gzip_fh:
                    gzip_fh.write(blob)
                raw_fh.flush()
                os.fsync(raw_fh.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return path

    def load(self, endpoint: str, request_hash: str) -> object | None:
        path = self._path(endpoint, request_hash)
        if not path.exists():
            return None
        with gzip.open(path, "rb") as fh:
            return json.loads(fh.read().decode("utf-8"))

    def exists(self, endpoint: str, request_hash: str) -> bool:
        return self._path(endpoint, request_hash).exists()

    def delete(self, endpoint: str, request_hash: str) -> None:
        path = self._path(endpoint, request_hash)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def payload_hash(payload: object) -> str:
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()
