"""Process-wide Cortex upstream concurrency regression tests."""

from __future__ import annotations

import threading
import time

import pytest

import app.clients.cortex.client as client_module
from app.clients.cortex.client import CortexClient
from app.clients.cortex.errors import CortexError, ErrorCode


def _bare_client() -> CortexClient:
    """The limiter/retry layer only needs a client object when _single_request is stubbed."""
    return CortexClient.__new__(CortexClient)


def test_distinct_upstream_requests_never_exceed_four_in_flight(monkeypatch):
    """Different requests may run concurrently, but the process-wide cap is four."""
    monkeypatch.setattr(
        client_module,
        "_UPSTREAM_SEMAPHORE",
        threading.BoundedSemaphore(client_module._MAX_CONCURRENT_UPSTREAM_REQUESTS),
    )
    client = _bare_client()
    worker_count = 12
    ready = threading.Barrier(worker_count)
    state_lock = threading.Lock()
    active = 0
    max_active = 0
    completed = []
    errors = []

    def fake_single_request(*_args, **_kwargs):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            return []
        finally:
            with state_lock:
                active -= 1

    client._single_request = fake_single_request

    def run(index: int) -> None:
        try:
            ready.wait(timeout=5)
            client._request_with_retry(
                "GET",
                "/v1/instruments",
                params={"worker": index},
                correlation_id=f"worker-{index}",
            )
            completed.append(index)
        except Exception as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert len(completed) == worker_count
    assert max_active <= client_module._MAX_CONCURRENT_UPSTREAM_REQUESTS
    assert max_active > 1, "the limiter should bound concurrency, not serialize all requests"


def test_upstream_slot_is_released_when_one_attempt_raises(monkeypatch):
    """The semaphore context must release its permit on every exception path."""
    semaphore = threading.BoundedSemaphore(1)
    monkeypatch.setattr(client_module, "_UPSTREAM_SEMAPHORE", semaphore)
    client = _bare_client()

    def fail_once(*_args, **_kwargs):
        raise CortexError(ErrorCode.INVALID_REQUEST, "synthetic failure")

    client._single_request = fail_once
    with pytest.raises(CortexError) as exc_info:
        client._request_with_retry(
            "GET",
            "/v1/instruments",
            correlation_id="failure",
        )
    assert exc_info.value.code == ErrorCode.INVALID_REQUEST

    # If the exception leaked the only permit this non-blocking acquire would fail.
    assert semaphore.acquire(blocking=False)
    semaphore.release()


def test_retry_releases_upstream_slot_during_backoff(monkeypatch):
    """A 429 retry re-enters the queue instead of sleeping while holding a permit."""
    semaphore = threading.BoundedSemaphore(1)
    monkeypatch.setattr(client_module, "_UPSTREAM_SEMAPHORE", semaphore)
    client = _bare_client()
    calls = 0
    backoff_saw_free_slot = False

    def rate_limit_then_succeed(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            error = CortexError(ErrorCode.UPSTREAM_RATE_LIMITED, "synthetic 429")
            error.retry_after = 0.01
            raise error
        return []

    def inspect_backoff(_seconds: float) -> None:
        nonlocal backoff_saw_free_slot
        backoff_saw_free_slot = semaphore.acquire(blocking=False)
        if backoff_saw_free_slot:
            semaphore.release()

    client._single_request = rate_limit_then_succeed
    monkeypatch.setattr(client_module.time, "sleep", inspect_backoff)
    result = client._request_with_retry(
        "GET",
        "/v1/instruments",
        correlation_id="retry",
    )

    assert result == []
    assert calls == 2
    assert backoff_saw_free_slot
    assert semaphore.acquire(blocking=False)
    semaphore.release()
