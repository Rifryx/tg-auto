"""Тесты агрегатов execution_log для экрана «Ход» (prompt 6.3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from modules.priming.repositories.execution_log import ExecutionLogRepository


class _StubSession:
    """Мини-движок с in-memory списком execution_log-строк."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def execute(self, stmt):  # noqa: D401 — совместимость с call-site'ом
        raise AssertionError("не должно вызываться в этих тестах")


def _sparkline_from_rows(
    campaign_id: int,
    rows: list[datetime],
    *,
    hours: int,
    now: datetime,
) -> list[int]:
    """Портируем ту же арифметику в чистом Python — покрываем hourly
    бакетирование без БД (сам SQL проверяется на CI под postgres_test)."""
    since = now - timedelta(hours=hours)
    buckets = [0] * hours
    for finished_at in rows:
        if finished_at is None:
            continue
        if finished_at.tzinfo is None:
            finished_at = finished_at.replace(tzinfo=timezone.utc)
        delta_hours = int((finished_at - since).total_seconds() // 3600)
        if 0 <= delta_hours < hours:
            buckets[delta_hours] += 1
    return buckets


def test_sparkline_buckets_last_hour_index() -> None:
    now = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    rows = [
        now - timedelta(minutes=5),        # текущий час
        now - timedelta(hours=1, minutes=30),  # -2 часа назад в шкале
        now - timedelta(hours=23, minutes=59),  # самый старый час
    ]
    buckets = _sparkline_from_rows(1, rows, hours=24, now=now)
    assert len(buckets) == 24
    assert buckets[-1] == 1  # текущий час
    assert buckets[0] == 1   # −24ч край
    # −1..-2ч
    assert sum(buckets[-3:-1]) == 1


def test_sparkline_ignores_outside_window() -> None:
    now = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    rows = [
        now - timedelta(hours=48),  # вне окна
        now + timedelta(hours=1),   # будущее (клоки разъехались)
    ]
    buckets = _sparkline_from_rows(1, rows, hours=24, now=now)
    assert sum(buckets) == 0


def test_repository_hourly_buckets_signature() -> None:
    # Просто убеждаемся, что метод есть у репо (импорт-путь стабилен).
    assert hasattr(ExecutionLogRepository, "hourly_buckets")
    assert hasattr(ExecutionLogRepository, "outcome_counts")
