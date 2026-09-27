"""Переиспользуемые фильтры аудитории (spec §8.2, промпт 3.2).

Каждый фильтр принимает поток «сырьевых» строк-кандидатов и возвращает
поток оставшихся. Отбрасывания считаются в общий словарь-разбивку
``breakdown: dict[str, int]``.

Форма кандидата — dict:
    {
      "tg_user_id": int | None,
      "username":   str | None,
      "phone":      str | None,
      "has_premium": bool | None,
      "is_bot":      bool,     # опционально
      "is_deleted":  bool,     # опционально
      "is_admin":    bool,     # опционально
      "last_seen_bucket": TargetLastSeen | None,
    }

Итоговая композиция — :func:`apply_filters`; она принимает набор опций и
последовательно прогоняет строки через нужные фильтры. Кандидат
отбрасывается ПЕРВОЙ причиной, чтобы breakdown не задваивал одну строку.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional

from modules.priming.repositories import BlacklistRepository


REASON_NO_USERNAME = "no_username"
REASON_NOT_PREMIUM = "not_premium"
REASON_BOT = "bot"
REASON_DELETED = "deleted"
REASON_ADMIN = "admin"
REASON_BLACKLISTED = "blacklisted"


@dataclass
class FilterOptions:
    require_username: bool = False
    premium_only: bool = False
    exclude_bots: bool = True
    exclude_deleted: bool = True
    exclude_admins: bool = True
    check_blacklist: bool = True
    owner_user_id: Optional[int] = None


@dataclass
class FilterOutcome:
    kept: list[dict] = field(default_factory=list)
    breakdown: dict[str, int] = field(default_factory=dict)

    def _drop(self, reason: str) -> None:
        self.breakdown[reason] = self.breakdown.get(reason, 0) + 1


# ---------------------------------------------------------------------------
# Простые «локальные» фильтры (без БД).
# ---------------------------------------------------------------------------


def filter_username(rows: Iterable[dict]) -> Iterator[tuple[Optional[dict], Optional[str]]]:
    """Отсекает без username. Используется, когда require_username=True."""
    for row in rows:
        if not row.get("username"):
            yield None, REASON_NO_USERNAME
        else:
            yield row, None


def filter_premium(rows: Iterable[dict]) -> Iterator[tuple[Optional[dict], Optional[str]]]:
    for row in rows:
        if row.get("has_premium") is not True:
            yield None, REASON_NOT_PREMIUM
        else:
            yield row, None


def filter_bots(rows: Iterable[dict]) -> Iterator[tuple[Optional[dict], Optional[str]]]:
    for row in rows:
        if row.get("is_bot"):
            yield None, REASON_BOT
        else:
            yield row, None


def filter_deleted(rows: Iterable[dict]) -> Iterator[tuple[Optional[dict], Optional[str]]]:
    for row in rows:
        if row.get("is_deleted"):
            yield None, REASON_DELETED
        else:
            yield row, None


def filter_admins(rows: Iterable[dict]) -> Iterator[tuple[Optional[dict], Optional[str]]]:
    for row in rows:
        if row.get("is_admin"):
            yield None, REASON_ADMIN
        else:
            yield row, None


# ---------------------------------------------------------------------------
# Blacklist — требует репозитория с БД-сессией.
# ---------------------------------------------------------------------------


def filter_blacklist(
    rows: Iterable[dict],
    *,
    blacklist_repo: BlacklistRepository,
    owner_user_id: Optional[int],
) -> Iterator[tuple[Optional[dict], Optional[str]]]:
    for row in rows:
        hit = blacklist_repo.match(
            owner_user_id=owner_user_id,
            tg_user_id=row.get("tg_user_id"),
            username=row.get("username"),
            phone=row.get("phone"),
        )
        if hit is not None:
            yield None, REASON_BLACKLISTED
        else:
            yield row, None


# ---------------------------------------------------------------------------
# Композиция
# ---------------------------------------------------------------------------


def apply_filters(
    rows: Iterable[dict],
    *,
    options: FilterOptions,
    blacklist_repo: Optional[BlacklistRepository] = None,
) -> FilterOutcome:
    """Прогоняет rows через настроенный набор фильтров.

    Порядок применения фиксирован — от самых дешёвых (username/bot/deleted)
    к самому дорогому (blacklist, ходит в БД). Одна строка отбрасывается
    ПЕРВОЙ подходящей причиной.
    """
    outcome = FilterOutcome()
    for row in rows:
        reason = _first_drop_reason(
            row,
            options=options,
            blacklist_repo=blacklist_repo,
        )
        if reason is None:
            outcome.kept.append(row)
        else:
            outcome._drop(reason)
    return outcome


def _first_drop_reason(
    row: dict,
    *,
    options: FilterOptions,
    blacklist_repo: Optional[BlacklistRepository],
) -> Optional[str]:
    if options.require_username and not row.get("username"):
        return REASON_NO_USERNAME
    if options.exclude_bots and row.get("is_bot"):
        return REASON_BOT
    if options.exclude_deleted and row.get("is_deleted"):
        return REASON_DELETED
    if options.exclude_admins and row.get("is_admin"):
        return REASON_ADMIN
    if options.premium_only and row.get("has_premium") is not True:
        return REASON_NOT_PREMIUM
    if options.check_blacklist and blacklist_repo is not None:
        hit = blacklist_repo.match(
            owner_user_id=options.owner_user_id,
            tg_user_id=row.get("tg_user_id"),
            username=row.get("username"),
            phone=row.get("phone"),
        )
        if hit is not None:
            return REASON_BLACKLISTED
    return None
