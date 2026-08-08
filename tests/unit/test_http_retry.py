import logging
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from app.clients.cortex.client import CortexClient, parse_retry_after
from app.clients.cortex.errors import CortexError, ErrorCode


def test_retry_after_supports_seconds_and_caps_wait():
    assert parse_retry_after("12") == 12
    assert parse_retry_after("999") == 60
    assert parse_retry_after("not-a-date") is None


def test_retry_after_supports_http_date():
    now = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    header = format_datetime(now + timedelta(seconds=20), usegmt=True)
    assert parse_retry_after(header, now=now) == pytest.approx(20)


def test_upstream_error_whitelists_message_code_and_suggested_action():
    client = object.__new__(CortexClient)
    response = httpx.Response(
        400,
        json={
            "code": "BNP_BAD_COORDINATE",
            "message": "Requested maturity/strike combination is unavailable.",
            "suggestedAction": "Try another observation date or coordinate.",
            "secretField": "must-not-be-attached",
        },
    )
    with pytest.raises(CortexError) as raised:
        client._handle_response(response, "test-cid")
    error = raised.value
    assert error.code == ErrorCode.INVALID_REQUEST
    assert error.upstream_code == "BNP_BAD_COORDINATE"
    assert error.upstream_message == "Requested maturity/strike combination is unavailable."
    assert error.upstream_suggested_action == "Try another observation date or coordinate."
    assert not hasattr(error, "upstream_payload")
    assert "secretField" not in error.__dict__


def test_upstream_error_log_never_records_unwhitelisted_response_body(caplog):
    client = object.__new__(CortexClient)
    response = httpx.Response(
        400,
        json={
            "code": "BNP_BAD_COORDINATE",
            "message": "Requested coordinate is unavailable.",
            "suggestedAction": "Try another coordinate.",
            "secretField": "RAW_BODY_SECRET_MARKER",
        },
    )

    with caplog.at_level(logging.WARNING, logger="cortex.client"):
        with pytest.raises(CortexError):
            client._handle_response(response, "log-boundary")

    log_text = caplog.text
    assert "BNP_BAD_COORDINATE" in log_text
    assert "Requested coordinate is unavailable." in log_text
    assert "RAW_BODY_SECRET_MARKER" not in log_text
    assert "secretField" not in log_text
    assert "suggestedAction" not in log_text


def test_upstream_non_json_error_uses_normalized_error_without_upstream_fields():
    client = object.__new__(CortexClient)
    response = httpx.Response(404, text="not json")
    with pytest.raises(CortexError) as raised:
        client._handle_response(response, "test-cid")
    error = raised.value
    assert error.code == ErrorCode.NO_DATA
    assert error.upstream_code is None
    assert error.upstream_message is None
    assert error.upstream_suggested_action is None
