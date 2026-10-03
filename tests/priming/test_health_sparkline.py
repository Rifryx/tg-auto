"""Health-биометрия аккаунта (prompt 7.5) — арифметика бакетирования
без БД (портируем ту же логику из репозитория в чистом Python)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _daily_health_from_rows(rows, *, days: int, now: datetime):
    since = now - timedelta(days=days)
    buckets = [
        {"successes": 0, "floods": 0, "privacy": 0} for _ in range(days)
    ]
    for finished_at, outcome in rows:
        if finished_at is None:
            continue
        if finished_at.tzinfo is None:
            finished_at = finished_at.replace(tzinfo=timezone.utc)
        delta_days = int((finished_at - since).total_seconds() // 86400)
        if not (0 <= delta_days < days):
            continue
        if outcome == "primed":
            buckets[delta_days]["successes"] += 1
        elif outcome == "flood_wait":
            buckets[delta_days]["floods"] += 1
        elif outcome == "privacy_restricted":
            buckets[delta_days]["privacy"] += 1
    return buckets


def test_seven_days_shape() -> None:
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    buckets = _daily_health_from_rows([], days=7, now=now)
    assert len(buckets) == 7
    assert all(
        b == {"successes": 0, "floods": 0, "privacy": 0} for b in buckets
    )


def test_events_land_in_correct_day() -> None:
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    rows = [
        (now - timedelta(minutes=5), "primed"),
        (now - timedelta(hours=25), "flood_wait"),   # −1 день
        (now - timedelta(days=6, hours=1), "privacy_restricted"),  # −(days-1)
    ]
    buckets = _daily_health_from_rows(rows, days=7, now=now)
    # -1 днём назад → 5, сегодня → 6, самый старый → 0
    assert buckets[-1]["successes"] == 1
    assert buckets[-2]["floods"] == 1
    assert buckets[0]["privacy"] == 1


def test_outside_window_ignored() -> None:
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    rows = [
        (now - timedelta(days=30), "primed"),
        (now + timedelta(hours=1), "primed"),
    ]
    buckets = _daily_health_from_rows(rows, days=7, now=now)
    assert sum(b["successes"] for b in buckets) == 0


def test_unknown_outcomes_ignored() -> None:
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    rows = [
        (now - timedelta(minutes=5), "already_applied"),
        (now - timedelta(minutes=5), "internal_error"),
    ]
    buckets = _daily_health_from_rows(rows, days=7, now=now)
    assert all(b == {"successes": 0, "floods": 0, "privacy": 0} for b in buckets)
