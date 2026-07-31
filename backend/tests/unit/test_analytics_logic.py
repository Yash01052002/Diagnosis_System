"""Unit tests for the analytics derived-figure helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.analytics import _mtbf_hours


def test_mtbf_needs_two_crashes() -> None:
    now = datetime.now(UTC)
    assert _mtbf_hours(0, None, None) is None
    assert _mtbf_hours(1, now, now) is None


def test_mtbf_divides_span_by_intervals() -> None:
    first = datetime(2026, 1, 1, tzinfo=UTC)
    last = first + timedelta(hours=48)
    # 3 crashes over 48h => 2 intervals => 24h.
    assert _mtbf_hours(3, first, last) == 24.0


def test_mtbf_two_crashes_is_full_span() -> None:
    first = datetime(2026, 1, 1, tzinfo=UTC)
    last = first + timedelta(hours=10)
    assert _mtbf_hours(2, first, last) == 10.0
