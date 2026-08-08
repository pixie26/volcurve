from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"pattern not found in {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Keep raw-store documentation accurate: raw is the short request-cache authority, while
# long-lived exact-series history is persisted separately after Step 7.
replace_once(
    "app/storage/raw_store.py",
'''"""Raw response store: the authoritative source of truth.

Every successful upstream response is persisted verbatim (gzip JSON) at
data/raw/{endpoint}/{request_hash}.json.gz. Normalized stores and the
DuckDB catalog are derivable from these files and can be rebuilt.
"""
''',
'''"""Verified raw request-cache store.

Every successful upstream response is first persisted verbatim (gzip JSON) at
``data/raw/{endpoint}/{request_hash}.json.gz``.  These files remain the authority for
an individual cached request while they are retained.  Step 7 may later compact expired
request files after an eligible exact series has been committed to the revision-aware
historical point library; therefore ``data/raw`` is no longer the permanent archive.
"""
''',
)

# Self-describing coordinate metadata for the long-lived history DB.
history_path = ROOT / "app/storage/history.py"
history = history_path.read_text(encoding="utf-8")
history = history.replace(
'''_POINTS_DDL = """
CREATE TABLE IF NOT EXISTS historical_points (
''',
'''_COORDINATES_DDL = """
CREATE TABLE IF NOT EXISTS historical_coordinates (
    coordinate_hash VARCHAR PRIMARY KEY,
    api_version     VARCHAR NOT NULL,
    coordinate_json VARCHAR NOT NULL,
    first_seen_at   TIMESTAMPTZ NOT NULL,
    last_seen_at    TIMESTAMPTZ NOT NULL
)
"""

_POINTS_DDL = """
CREATE TABLE IF NOT EXISTS historical_points (
''',
1,
)
history = history.replace(
'''        with self._lock:
            self._conn.execute(_POINTS_DDL)
            self._conn.execute(_COVERAGE_DDL)
            self._conn.execute(_REVISIONS_DDL)
''',
'''        with self._lock:
            self._conn.execute(_COORDINATES_DDL)
            self._conn.execute(_POINTS_DDL)
            self._conn.execute(_COVERAGE_DDL)
            self._conn.execute(_REVISIONS_DDL)
''',
1,
)
history = history.replace(
'''        correlation_id: str,
        observations: list[StandardObservation],
    ) -> None:
''',
'''        correlation_id: str,
        observations: list[StandardObservation],
        api_version: str = "unknown",
        coordinate_json: str = "{}",
    ) -> None:
''',
1,
)
history = history.replace(
'''            self._conn.execute("BEGIN TRANSACTION")
            try:
                rows = self._conn.execute(
''',
'''            self._conn.execute("BEGIN TRANSACTION")
            try:
                coordinate_row = self._conn.execute(
                    "SELECT first_seen_at, last_seen_at FROM historical_coordinates "
                    "WHERE coordinate_hash = ?",
                    [coordinate_hash],
                ).fetchone()
                first_seen = coordinate_row[0] if coordinate_row is not None else retrieved_at
                last_seen = (
                    max(coordinate_row[1], retrieved_at)
                    if coordinate_row is not None
                    else retrieved_at
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO historical_coordinates VALUES (?, ?, ?, ?, ?)",
                    [coordinate_hash, api_version, coordinate_json, first_seen, last_seen],
                )
                rows = self._conn.execute(
''',
1,
)
insert = '''
    def coordinate_metadata(self, coordinate_hash: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT api_version, coordinate_json, first_seen_at, last_seen_at "
                "FROM historical_coordinates WHERE coordinate_hash = ?",
                [coordinate_hash],
            ).fetchone()
        if row is None:
            return None
        return {
            "api_version": row[0],
            "coordinate_json": row[1],
            "first_seen_at": row[2],
            "last_seen_at": row[3],
        }

'''
marker = "    def revision_count(self, coordinate_hash: str | None = None) -> int:\n"
if marker not in history:
    raise RuntimeError("history insertion marker missing")
history = history.replace(marker, insert + marker, 1)
history_path.write_text(history, encoding="utf-8")

# Cortex client hardening after code review.
client_path = ROOT / "app/clients/cortex/client.py"
client = client_path.read_text(encoding="utf-8")
client = client.replace(
'''        # Absolute/fixed strikes can have very high cardinality and are deliberately
        # short-cache only, regardless of whether the maturity rule is fixed or listed.
        return not isinstance(request, FixedStrikeRequest) and False
''',
'''        # Absolute/fixed strikes and non-exact ranges can have high cardinality and are
        # deliberately short-cache only.
        return False
''',
1,
)
# Store canonical coordinate metadata alongside the opaque hash.
old_archive = '''            history.upsert_series(
                coordinate_hash=coordinate_hash,
                request_hash=request_hash,
                start_date=request.start_date,
                end_date=request.end_date,
                retrieved_at=result.retrieved_at,
                response_hash=RawStore.payload_hash(result.payload),
                correlation_id=result.correlation_id,
                observations=observations,
            )
'''
new_archive = '''            wire = serialize_volatility_request(request)
            coordinate_json = json.dumps(
                {key: value for key, value in wire.items() if key not in {"startDate", "endDate"}},
                sort_keys=True,
                separators=(",", ":"),
            )
            history.upsert_series(
                coordinate_hash=coordinate_hash,
                request_hash=request_hash,
                start_date=request.start_date,
                end_date=request.end_date,
                retrieved_at=result.retrieved_at,
                response_hash=RawStore.payload_hash(result.payload),
                correlation_id=result.correlation_id,
                observations=observations,
                api_version=self.api_version,
                coordinate_json=coordinate_json,
            )
'''
if old_archive not in client:
    raise RuntimeError("archive block missing")
client = client.replace(old_archive, new_archive, 1)

# A successful HTTP response can still normalize to NO_DATA (e.g. empty payload).  When
# this was an actual refresh, apply the same explicit stale fallback policy as a 404.
old_pipeline = '''        canonical = self._canonicalize_implied_volatility(
            request, request_hash, request_json, policy, result
        )
        try:
            observations = normalize_surface(canonical, request)
        except CortexError as exc:
            self._record_parse_failure(request, request_hash, request_json, policy, result, exc)
            raise
        observations = _within_requested_range(observations, request, result)
        if not observations:
            raise CortexError(ErrorCode.NO_DATA, "该日期区间内没有可用观测")
        self._finish_implied_volatility(
'''
new_pipeline = '''        try:
            canonical = self._canonicalize_implied_volatility(
                request, request_hash, request_json, policy, result
            )
            try:
                observations = normalize_surface(canonical, request)
            except CortexError as exc:
                if exc.code != ErrorCode.NO_DATA:
                    self._record_parse_failure(
                        request, request_hash, request_json, policy, result, exc
                    )
                raise
            observations = _within_requested_range(observations, request, result)
            if not observations:
                raise CortexError(ErrorCode.NO_DATA, "该日期区间内没有可用观测")
        except CortexError as exc:
            if (
                eligible
                and result.cache_status == "live"
                and self._stale_fallback_allowed(exc)
            ):
                exc.correlation_id = result.correlation_id
                archived = self._load_history_result(
                    request, coordinate_hash, fresh_after=None, stale_error=exc
                )
                if archived is not None:
                    return archived
            raise
        self._finish_implied_volatility(
'''
if old_pipeline not in client:
    raise RuntimeError("series pipeline block missing")
client = client.replace(old_pipeline, new_pipeline, 1)

# NO_DATA is ordinary data availability, not a parser failure.
client = client.replace(
'''        try:
            canonical = canonicalize_surface(result.payload)
        except CortexError as exc:
            self._record_parse_failure(request, request_hash, request_json, policy, result, exc)
            raise
''',
'''        try:
            canonical = canonicalize_surface(result.payload)
        except CortexError as exc:
            if exc.code != ErrorCode.NO_DATA:
                self._record_parse_failure(request, request_hash, request_json, policy, result, exc)
            raise
''',
1,
)

# Determine whether an old wire request belongs to the exact-series historical tier.  This
# lets cleanup safely remove all other expired range/surface/absolute cache files while
# retaining pre-Step-7 exact-series raws until they have been migrated to history.
marker = '''    def _prune_expired_request_files(self, now: datetime) -> None:
'''
helper = '''    @staticmethod
    def _wire_history_eligible(body: dict) -> bool:
        strike_rule = body.get("strikeRule")
        maturity_rule = body.get("maturityRule")
        if strike_rule == "fixed":
            return False
        if strike_rule == "delta":
            return bool(
                body.get("lowDeltaStrike")
                and body.get("lowDeltaStrike") == body.get("highDeltaStrike")
                and body.get("lowMaturity")
                and body.get("lowMaturity") == body.get("highMaturity")
            )
        if strike_rule not in {"relative_to_forward", "relative_to_spot_ref"}:
            return False
        if not body.get("lowStrike") or body.get("lowStrike") != body.get("highStrike"):
            return False
        if maturity_rule == "sliding":
            return bool(
                body.get("lowMaturity")
                and body.get("lowMaturity") == body.get("highMaturity")
            )
        if maturity_rule in {"fixed", "listed"}:
            return bool(
                body.get("lowFixedMaturity")
                and body.get("lowFixedMaturity") == body.get("highFixedMaturity")
            )
        return False

'''
if marker not in client:
    raise RuntimeError("prune marker missing")
client = client.replace(marker, helper + marker, 1)
old_prune_head = '''            request_json = entry.get("request_json") or ""
            try:
                strike_rule = json.loads(request_json).get("strikeRule")
            except (TypeError, ValueError, json.JSONDecodeError):
                strike_rule = None
            archived = False
'''
new_prune_head = '''            request_json = entry.get("request_json") or ""
            try:
                wire_body = json.loads(request_json)
            except (TypeError, ValueError, json.JSONDecodeError):
                # Unknown legacy metadata is kept rather than risking data loss.
                continue
            history_eligible = self._wire_history_eligible(wire_body)
            archived = False
'''
if old_prune_head not in client:
    raise RuntimeError("prune head missing")
client = client.replace(old_prune_head, new_prune_head, 1)
old_prune_policy = '''            # Fixed/absolute strike universes are explicitly non-historical. Exact
            # percentage/delta request files may also be dropped once point history covers
            # them. Surface/range responses without durable history are retained for now.
            if strike_rule != "fixed" and not archived:
                continue
'''
new_prune_policy = '''            # Every non-historical request is short-cache only.  Eligible exact percentage/
            # delta raws are retained solely until their interval has been migrated into the
            # point library, which protects upgrades from pre-Step-7 installations.
            if history_eligible and not archived:
                continue
'''
if old_prune_policy not in client:
    raise RuntimeError("prune policy missing")
client = client.replace(old_prune_policy, new_prune_policy, 1)
client_path.write_text(client, encoding="utf-8")

# Documentation: all non-history surfaces/ranges are short cache, not just fixed strikes.
phase_path = ROOT / "docs/phase_f_compare_indicator_builder_zh.md"
phase = phase_path.read_text(encoding="utf-8")
phase = phase.replace(
'- 长期历史库只收 **K/F 百分比、K/S 百分比与 Delta** 的精确单坐标序列；absolute/fixed strike（包括 listed strike discovery 的大 strike universe）只保留短期 request cache，不进入历史点库。\n',
'- 长期历史库只收 **K/F 百分比、K/S 百分比与 Delta** 的精确单坐标序列；absolute/fixed strike（包括 listed strike discovery 的大 strike universe）以及非精确 range/surface 都只保留 8 小时 request cache，不进入历史点库。\n',
1,
)
phase_path.write_text(phase, encoding="utf-8")

# Additional deep tests found useful during review: newest broad cache precedence, actual
# 8-hour client refresh, delta persistence, live-200 NO_DATA fallback, coordinate metadata,
# and short-cache deletion for non-historical surfaces.
test_path = ROOT / "tests/unit/test_historical_archive.py"
tests = test_path.read_text(encoding="utf-8")
tests = tests.replace(
'from app.clients.cortex.serializers import volatility_coordinate_hash\n',
'from app.clients.cortex.serializers import serialize_volatility_request, volatility_coordinate_hash\n',
1,
)
tests += r'''


def _complete_raw_cache(client, req, raw_payload, retrieved_at):
    request_hash = req.request_hash(client.api_version)
    coordinate_hash = volatility_coordinate_hash(req, client.api_version)
    body = serialize_volatility_request(req)
    response_hash = RawStore.payload_hash(raw_payload)
    client._raw.save("implied-volatility", request_hash, raw_payload)
    client._catalog.upsert(
        request_hash=request_hash,
        endpoint="implied-volatility",
        api_version=client.api_version,
        instrument=req.code,
        start_date=req.start_date,
        end_date=req.end_date,
        request_json=__import__("json").dumps(body, sort_keys=True),
        response_hash=response_hash,
        retrieved_at=retrieved_at,
        status="COMPLETED",
        cache_policy="historical",
        correlation_id=request_hash,
        quality_status="OK",
        coordinate_hash=coordinate_hash,
    )
    return request_hash


def test_newer_wider_raw_cache_beats_older_exact_cache(tmp_path):
    client = bare_client(tmp_path, history=False)
    narrow = request("2026-02-01", "2026-03-01")
    wide = request("2026-01-01", "2026-04-01")
    now = datetime.now(UTC)
    _complete_raw_cache(client, narrow, payload([("2026-02-15", .20)]), now - timedelta(hours=2))
    wide_hash = _complete_raw_cache(
        client,
        wide,
        payload([("2026-01-15", .19), ("2026-02-15", .25), ("2026-03-15", .23)]),
        now - timedelta(hours=1),
    )
    chosen = client._best_cached_result(
        narrow,
        request_hash=narrow.request_hash(client.api_version),
        coordinate_hash=volatility_coordinate_hash(narrow, client.api_version),
        require_fresh=True,
    )
    assert chosen is not None
    assert chosen.source_request_hash == wide_hash
    assert chosen.cache_status == "cache"


def test_cache_older_than_eight_hours_reaches_upstream(tmp_path):
    client = bare_client(tmp_path, history=False)
    req = request("2026-01-01", "2026-01-31")
    _complete_raw_cache(
        client,
        req,
        payload([("2026-01-15", .20)]),
        datetime.now(UTC) - timedelta(hours=8, minutes=1),
    )
    calls = []
    client._request_with_retry = lambda *_a, **_k: (
        calls.append(1) or payload([("2026-01-15", .21)])
    )
    observations, result = client.get_implied_volatility(req)
    assert calls == [1]
    assert result.cache_status == "live"
    assert observations[0].implied_vol == .21


def test_delta_series_is_actually_archived_and_reused(tmp_path):
    client = bare_client(tmp_path)
    req = SlidingDeltaRequest(
        code="US_QQQ",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        low_delta_strike="p25.0",
        high_delta_strike="p25.0",
        low_maturity="3M",
        high_maturity="3M",
    )
    delta_payload = [{
        "date": "2026-01-15",
        "code": "US_QQQ",
        "maturityRule": "sliding",
        "strikeRule": "delta",
        "volatilityConvention": "bsVol",
        "spot": 500.0,
        "maturities": ["3M"],
        "strikes": ["p25.0"],
        "forwardCurve": [501.0],
        "zcCurve": [0.99],
        "matrix": [[0.27]],
    }]
    calls = []
    client._request_with_retry = lambda *_a, **_k: calls.append(1) or delta_payload
    first, _ = client.get_implied_volatility(req)
    second, result = client.get_implied_volatility(req)
    assert len(calls) == 1
    assert first[0].implied_vol == second[0].implied_vol == .27
    assert result.cache_status == "archive"


def test_live_200_no_data_can_fall_back_to_stale_archive(tmp_path):
    client = bare_client(tmp_path)
    req = request("2026-01-01", "2026-01-31")
    coord = volatility_coordinate_hash(req, client.api_version)
    old = datetime.now(UTC) - timedelta(hours=9)
    client._history.upsert_series(
        coordinate_hash=coord,
        request_hash="old",
        start_date=req.start_date,
        end_date=req.end_date,
        retrieved_at=old,
        response_hash="old",
        correlation_id="old-cid",
        observations=[obs("2026-01-15", .20)],
        api_version=client.api_version,
        coordinate_json="{}",
    )
    client._request_with_retry = lambda *_a, **_k: []
    observations, result = client.get_implied_volatility(req)
    assert observations[0].implied_vol == .20
    assert result.cache_status == "stale"
    assert result.stale_reason.startswith("NO_DATA")
    assert result.refresh_correlation_id


def test_history_coordinate_hash_remains_self_describing_after_cache_compaction(tmp_path):
    client = bare_client(tmp_path)
    req = request("2026-01-01", "2026-01-31")
    client._request_with_retry = lambda *_a, **_k: payload([("2026-01-15", .20)])
    client.get_implied_volatility(req)
    coord = volatility_coordinate_hash(req, client.api_version)
    metadata = client._history.coordinate_metadata(coord)
    assert metadata is not None
    assert metadata["api_version"] == client.api_version
    wire = __import__("json").loads(metadata["coordinate_json"])
    assert "startDate" not in wire and "endDate" not in wire
    assert wire["code"] == "US_QQQ"
    assert wire["lowStrike"] == wire["highStrike"] == "100_0"


def test_expired_nonhistorical_relative_surface_cache_is_pruned(tmp_path):
    client = bare_client(tmp_path)
    surface = SlidingMoneynessRequest(
        code="US_QQQ",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        low_strike=95,
        high_strike=105,
        low_maturity="1M",
        high_maturity="3M",
    )
    old_hash = _complete_raw_cache(
        client,
        surface,
        payload([("2026-01-15", .20)]),
        datetime.now(UTC) - timedelta(hours=9),
    )
    assert client._raw.exists("implied-volatility", old_hash)
    client._prune_expired_request_files(datetime.now(UTC))
    assert client._catalog.get(old_hash) is None
    assert not client._raw.exists("implied-volatility", old_hash)


def test_expired_unmigrated_exact_series_raw_is_retained_for_upgrade_safety(tmp_path):
    client = bare_client(tmp_path)
    req = request("2026-01-01", "2026-01-31")
    old_hash = _complete_raw_cache(
        client,
        req,
        payload([("2026-01-15", .20)]),
        datetime.now(UTC) - timedelta(hours=9),
    )
    client._prune_expired_request_files(datetime.now(UTC))
    assert client._catalog.get(old_hash) is not None
    assert client._raw.exists("implied-volatility", old_hash)
'''
test_path.write_text(tests, encoding="utf-8")

print("Step 7 review fixes applied")
