"""Переиспользуемые фильтры аудитории (spec §8.2, промпт 3.2b).

Живут в модуле-сервисе ``parsing``. Прайминг использует их только
косвенно — импортируя готовые списки через ``POST /import-list``.

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

import re
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional

from modules.priming.repositories import BlacklistRepository


REASON_NO_USERNAME = "no_username"
REASON_NOT_PREMIUM = "not_premium"
REASON_BOT = "bot"
REASON_DELETED = "deleted"
REASON_ADMIN = "admin"
REASON_BLACKLISTED = "blacklisted"
# Extraction+ (этап 1):
REASON_NO_PHOTO = "no_photo"
REASON_NOT_VERIFIED = "not_verified"
REASON_SCAM_FAKE = "scam_fake"
REASON_NO_PHONE = "no_phone"
REASON_USERNAME_REGEX = "username_regex"
REASON_NAME_SCRIPT = "name_script"
REASON_LAST_SEEN_OLD = "last_seen_too_old"


_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_LATIN = re.compile(r"[A-Za-z]")


def _full_name(row: dict) -> str:
    return f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()


def _matches_script(name: str, script: str) -> bool:
    """Есть ли в имени символы требуемого алфавита (cyrillic/latin)."""
    if not name:
        return False
    if script == "cyrillic":
        return bool(_CYRILLIC.search(name))
    if script == "latin":
        return bool(_LATIN.search(name))
    return True


@dataclass
class FilterOptions:
    require_username: bool = False
    premium_only: bool = False
    exclude_bots: bool = True
    exclude_deleted: bool = True
    exclude_admins: bool = True
    check_blacklist: bool = True
    owner_user_id: Optional[int] = None
    # Extraction+ (этап 1): профиль/активность.
    require_photo: bool = False
    verified_only: bool = False
    exclude_scam_fake: bool = True
    require_phone_visible: bool = False
    username_regex: Optional[str] = None
    name_script: Optional[str] = None  # "cyrillic" | "latin" | None
    last_seen_max_days: Optional[int] = None

    def compiled_username_regex(self) -> Optional["re.Pattern[str]"]:
        if not self.username_regex:
            return None
        try:
            return re.compile(self.username_regex, re.IGNORECASE)
        except re.error:
            return None


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
    if options.exclude_scam_fake and (row.get("is_scam") or row.get("is_fake")):
        return REASON_SCAM_FAKE
    if options.premium_only and row.get("has_premium") is not True:
        return REASON_NOT_PREMIUM
    if options.require_photo and not row.get("has_photo"):
        return REASON_NO_PHOTO
    if options.verified_only and not row.get("is_verified"):
        return REASON_NOT_VERIFIED
    if options.require_phone_visible and not row.get("phone"):
        return REASON_NO_PHONE
    if options.name_script and not _matches_script(_full_name(row), options.name_script):
        return REASON_NAME_SCRIPT
    if options.username_regex:
        pattern = options.compiled_username_regex()
        uname = row.get("username") or ""
        if pattern is not None and not pattern.search(uname):
            return REASON_USERNAME_REGEX
    if options.last_seen_max_days is not None:
        days = row.get("last_seen_days")
        # None (неизвестно) не отбрасываем — только явно «слишком старых».
        if days is not None and days > options.last_seen_max_days:
            return REASON_LAST_SEEN_OLD
    if options.check_blacklist and blacklist_repo is not None:
        hit = blacklist_repo.match(
            owner_user_id=options.owner_user_id,
            tg_user_id=row.get("tg_user_id"),
            username=row.get("username"),
            phone=row.get("phone"),
        )
        if hit is not None:
            return REASON_BLACKLISTED
        cross = blacklist_repo.match_cross_module(
            owner_user_id=options.owner_user_id,
            tg_user_id=row.get("tg_user_id"),
            username=row.get("username"),
            phone=row.get("phone"),
        )
        if cross is not None:
            return REASON_BLACKLISTED
    return None
