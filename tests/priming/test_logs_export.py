"""Тесты стримингового CSV-экспорта (prompt 6.4).

Проверяем логику итератора без БД: подменяем ``list_by_campaign`` на
in-memory paginator, чтобы убедиться, что ``iter_for_export`` корректно
двигает keyset и останавливается на неполной странице.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from modules.priming.repositories.execution_log import ExecutionLogRepository


@dataclass
class _Row:
    id: int


class _StubRepo:
    """Имитирует ExecutionLogRepository с in-memory списком id-строк."""

    def __init__(self, ids: list[int]) -> None:
        # Хранение в порядке DESC — как реальный SQL.
        self._ids = sorted(ids, reverse=True)

    def list_by_campaign(
        self,
        campaign_id: int,
        *,
        outcome: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 100,
        after_id: Optional[int] = None,
    ) -> list[_Row]:
        # Фильтр: id < after_id (id DESC).
        source = [i for i in self._ids if after_id is None or i < after_id]
        return [_Row(i) for i in source[:limit]]

    # Реюзаем реальный итератор:
    iter_for_export = ExecutionLogRepository.iter_for_export


def test_iter_for_export_streams_in_batches() -> None:
    ids = list(range(1, 8))  # 1..7
    repo = _StubRepo(ids)
    got = list(repo.iter_for_export(campaign_id=1, batch_size=3))
    # DESC порядок сохраняется, все 7 записей отданы ровно один раз.
    assert [r.id for r in got] == [7, 6, 5, 4, 3, 2, 1]


def test_iter_for_export_empty() -> None:
    repo = _StubRepo([])
    assert list(repo.iter_for_export(campaign_id=1)) == []


def test_iter_for_export_stops_on_partial_page() -> None:
    ids = list(range(1, 5))  # 1..4, batch_size=10 → одна страница, partial
    repo = _StubRepo(ids)
    got = list(repo.iter_for_export(campaign_id=1, batch_size=10))
    assert [r.id for r in got] == [4, 3, 2, 1]
