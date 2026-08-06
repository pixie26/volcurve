from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from app.clients.cortex.client import parse_retry_after


def test_retry_after_supports_seconds_and_caps_wait():
    assert parse_retry_after("12") == 12
    assert parse_retry_after("999") == 60
    assert parse_retry_after("not-a-date") is None


def test_retry_after_supports_http_date():
    now = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    header = format_datetime(now + timedelta(seconds=20), usegmt=True)
    assert parse_retry_after(header, now=now) == pytest.approx(20)
