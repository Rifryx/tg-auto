"""Схемы для поиска целей «по пересечению каналов».

Находит каналы с открытыми комментариями, на которые подписаны сразу
несколько аккаунтов кампании (см. TargetsTab → «По пересечению каналов»).
Результат отдаётся через SSE-поток ``shilling.intersection.{job_id}``.
"""

from __future__ import annotations

from pydantic import BaseModel


class DiscoveredChannel(BaseModel):
    """Найденный канал-пересечение (только с открытыми комментариями)."""

    chat_id: int
    username: str | None = None
    title: str | None = None
    # Канонический raw_input для добавления в цели (совпадает с normalize_target).
    raw_input: str
    # Сколько из просканированных аккаунтов подписаны на этот канал.
    subscriber_count: int
    # Уже ли этот канал добавлен в цели кампании.
    already_target: bool = False


class IntersectionReport(BaseModel):
    job_id: str
    ok: bool
    reason: str | None = None  # почему не удалось (нет аккаунтов и т.п.)
    channels: list[DiscoveredChannel] = []
    accounts_total: int = 0  # сколько аккаунтов пытались просканировать
    accounts_scanned: int = 0  # сколько реально удалось (не забанены, доступны)
    min_accounts: int = 2  # порог пересечения, по которому отфильтровано
