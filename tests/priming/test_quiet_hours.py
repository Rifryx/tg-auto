"""TZ-aware проверка «тихих часов» (prompt 7.2)."""

from __future__ import annotations

from datetime import datetime, timezone

from modules.priming.worker.quiet_hours import (
    QUIET_END_HOUR,
    QUIET_START_HOUR,
    is_quiet_hour_for,
)


def test_none_tz_never_blocks() -> None:
    assert is_quiet_hour_for(None) is False
    assert is_quiet_hour_for("") is False


def test_unknown_tz_never_blocks() -> None:
    assert is_quiet_hour_for("Not/AZone") is False


def test_moscow_night_is_quiet() -> None:
    # 03:00 в Москве — 00:00 UTC (MSK = UTC+3).
    utc = datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc)
    assert is_quiet_hour_for("Europe/Moscow", now=utc) is True


def test_moscow_morning_is_not_quiet() -> None:
    # 10:00 в Москве — 07:00 UTC.
    utc = datetime(2026, 6, 15, 7, 0, tzinfo=timezone.utc)
    assert is_quiet_hour_for("Europe/Moscow", now=utc) is False


def test_quiet_window_boundaries_inclusive_start_exclusive_end() -> None:
    utc = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    # UTC 12:00 — точно НЕ ночь ни в одной европейской TZ.
    assert is_quiet_hour_for("UTC", now=utc) is False
    # Задаём час 0 (start) → блокируем; час end → не блокируем.
    at_start = datetime(2026, 6, 15, 0, 30, tzinfo=timezone.utc)
    assert is_quiet_hour_for("UTC", now=at_start) is True
    at_end = datetime(2026, 6, 15, 7, 0, tzinfo=timezone.utc)
    assert is_quiet_hour_for("UTC", now=at_end) is False


def test_naive_datetime_treated_as_utc() -> None:
    naive = datetime(2026, 6, 15, 2, 0)  # без tzinfo
    assert is_quiet_hour_for("UTC", now=naive) is True


def test_default_window_matches_constants() -> None:
    assert QUIET_START_HOUR == 0
    assert QUIET_END_HOUR == 7
