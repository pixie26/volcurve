"""Gate E secret scan for candidate files and the complete reachable Git history.

The scanner never prints a matched value. It checks both generic credential
shapes and the credentials currently loaded from the environment, so an exact
accidental commit is detected without disclosing the value in logs.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PRIVATE_KEY = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
ASSIGNED_SECRET = re.compile(
    rb"(?i)(?:BNP_CLIENT_SECRET|client[_-]?secret|api[_-]?key|access[_-]?token)"
    rb"\s*[:=]\s*[\"']([^\"'\r\n]{12,})[\"']"
)
SAFE_MARKERS = (
    b"example",
    b"placeholder",
    b"changeme",
    b"your_",
    b"test-",
    b"<",
    b"${",
    b"xxxx",
)
GENERIC_EXCLUSIONS = ("app/web/vendor/", "docs/bnp/raw/")


@dataclass(frozen=True)
class Finding:
    detector: str
    location: str


def _generic_findings(blob: bytes, location: str) -> list[Finding]:
    findings = []
    if PRIVATE_KEY.search(blob):
        findings.append(Finding("private_key", location))
    normalized_location = location.replace("\\", "/")
    if not normalized_location.startswith(GENERIC_EXCLUSIONS):
        for match in ASSIGNED_SECRET.finditer(blob):
            value = match.group(1).strip().lower()
            if value and not any(marker in value for marker in SAFE_MARKERS):
                findings.append(Finding("assigned_secret", location))
    return findings


def _configured_values() -> list[bytes]:
    values: list[bytes] = []
    dotenv = dotenv_values(PROJECT_ROOT / ".env")
    for name in ("BNP_CLIENT_ID", "BNP_CLIENT_SECRET"):
        value = (os.getenv(name) or dotenv.get(name) or "").strip()
        if len(value) >= 8:
            values.append(value.encode())
    return values


def _candidate_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def _history_blobs() -> list[tuple[str, str]]:
    """Return every unique (path, blob) pair reachable from any Git ref."""
    commits = subprocess.run(
        ["git", "rev-list", "--all"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    pairs: set[tuple[str, str]] = set()
    for commit in commits:
        tree = subprocess.run(
            ["git", "ls-tree", "-r", "-z", "--full-tree", commit],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
        ).stdout
        for record in tree.split(b"\0"):
            if not record:
                continue
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split()
            if kind != "blob" or mode == "160000":
                continue
            pairs.add((raw_path.decode("utf-8"), object_id))
    return sorted(pairs)


def _read_blob(object_id: str) -> bytes:
    return subprocess.run(
        ["git", "cat-file", "blob", object_id],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def scan_repository() -> list[Finding]:
    findings: list[Finding] = []
    configured = _configured_values()
    for relative in _candidate_files():
        path = PROJECT_ROOT / relative
        if not path.is_file():
            continue
        blob = path.read_bytes()
        findings.extend(_generic_findings(blob, relative))
        if any(value in blob for value in configured):
            findings.append(Finding("configured_value", relative))

    blob_cache: dict[str, bytes] = {}
    for relative, object_id in _history_blobs():
        normalized = relative.replace("\\", "/")
        if normalized.startswith(GENERIC_EXCLUSIONS):
            continue
        blob = blob_cache.setdefault(object_id, _read_blob(object_id))
        location = f"git_history:{relative}"
        findings.extend(_generic_findings(blob, location))
        if any(value in blob for value in configured):
            findings.append(Finding("configured_value", location))
    return list(dict.fromkeys(findings))


def main() -> int:
    findings = scan_repository()
    if findings:
        print(f"secret scan: FAIL ({len(findings)} findings; values suppressed)")
        for finding in findings:
            print(f"- {finding.detector}: {finding.location}")
        return 1
    print("secret scan: PASS (candidate files + complete reachable Git history)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
