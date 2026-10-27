"""Фильтры сообществ (Discovery, этап 2).

Форма кандидата — dict со снапшотом канала/чата:
    kind, is_public, participants_count, has_linked_chat, last_post_days,
    is_verified, is_scam, is_fake, title, username, about, slowmode_seconds,
    noforwards.
Кандидат отбрасывается ПЕРВОЙ подходящей причиной.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

REASON_WRONG_KIND = "wrong_kind"
REASON_TOO_FEW = "too_few_participants"
REASON_TOO_MANY = "too_many_participants"
REASON_NOT_PUBLIC = "not_public"
REASON_NO_LINKED_CHAT = "no_linked_chat"
REASON_POST_TOO_OLD = "post_too_old"
REASON_SCAM_FAKE = "scam_fake"
REASON_NOT_VERIFIED = "not_verified"
REASON_TITLE_REGEX = "title_regex"
REASON_USERNAME_REGEX = "username_regex"
REASON_TITLE_EXCLUDE = "title_exclude"
REASON_WRONG_LANGUAGE = "wrong_language"
REASON_NOFORWARDS = "noforwards_blocked"
REASON_SLOWMODE_TOO_LOW = "slowmode_too_low"
REASON_SLOWMODE_TOO_HIGH = "slowmode_too_high"

# Какие алфавиты считаем "русским" / "английским". Эвристика смотрит на долю
# букв каждого скрипта в title+about. Пороги подобраны так, чтобы смешанные
# тексты попадали в "mixed", а не ошибочно блокировались.
_CYR_RE = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґЎў]")
_LAT_RE = re.compile(r"[A-Za-z]")


def _detect_language(text: str) -> str:
    """Возвращает "ru" / "en" / "mixed" / "unknown" по эвристике скриптов.

    Эвристика намеренно простая: без внешних библиотек, работает оффлайн,
    достаточна для грубой фильтрации (отсеять арабские/азиатские каналы при
    выборе "русский или английский")."""
    if not text:
        return "unknown"
    cyr = len(_CYR_RE.findall(text))
    lat = len(_LAT_RE.findall(text))
    total = cyr + lat
    if total < 3:
        return "unknown"
    cyr_ratio = cyr / total
    lat_ratio = lat / total
    if cyr_ratio >= 0.7:
        return "ru"
    if lat_ratio >= 0.7:
        return "en"
    return "mixed"


@dataclass
class CommunityFilterOptions:
    kind: Optional[str] = None  # "channel" | "chat" | None(любой)
    min_participants: Optional[int] = None
    max_participants: Optional[int] = None
    require_public: bool = False
    require_linked_chat: bool = False
    last_post_max_days: Optional[int] = None
    exclude_scam_fake: bool = True
    verified_only: bool = False
    title_regex: Optional[str] = None
    username_regex: Optional[str] = None
    # Новые точечные фильтры.
    title_exclude_regex: Optional[str] = None
    # "ru" | "en" | "ru_or_en" | None — язык определяется по title+about.
    # "unknown" тексты пропускаются (нет контента для анализа).
    language: Optional[str] = None
    # True → разрешены каналы c noforwards (запрет пересылки). False →
    # отсеиваем, если хотим иметь возможность форвардить/анализировать посты.
    allow_noforwards: bool = True
    # Slowmode (сек). None = не фильтровать. Применимо только к чатам/группам.
    min_slowmode_seconds: Optional[int] = None
    max_slowmode_seconds: Optional[int] = None

    def _rx(self, pattern: Optional[str]) -> Optional["re.Pattern[str]"]:
        if not pattern:
            return None
        try:
            return re.compile(pattern, re.IGNORECASE)
        except re.error:
            return None


def first_community_drop_reason(
    row: dict, options: CommunityFilterOptions
) -> Optional[str]:
    if options.kind and row.get("kind") != options.kind:
        return REASON_WRONG_KIND
    if options.exclude_scam_fake and (row.get("is_scam") or row.get("is_fake")):
        return REASON_SCAM_FAKE
    if options.verified_only and not row.get("is_verified"):
        return REASON_NOT_VERIFIED
    if options.require_public and not row.get("is_public"):
        return REASON_NOT_PUBLIC
    if options.require_linked_chat and not row.get("has_linked_chat"):
        return REASON_NO_LINKED_CHAT

    pc = row.get("participants_count")
    if options.min_participants is not None:
        if pc is None or pc < options.min_participants:
            return REASON_TOO_FEW
    if options.max_participants is not None:
        if pc is not None and pc > options.max_participants:
            return REASON_TOO_MANY

    if options.last_post_max_days is not None:
        days = row.get("last_post_days")
        if days is None or days > options.last_post_max_days:
            return REASON_POST_TOO_OLD

    if options.title_regex:
        rx = options._rx(options.title_regex)
        if rx is not None and not rx.search(row.get("title") or ""):
            return REASON_TITLE_REGEX
    if options.username_regex:
        rx = options._rx(options.username_regex)
        if rx is not None and not rx.search(row.get("username") or ""):
            return REASON_USERNAME_REGEX

    if options.title_exclude_regex:
        rx = options._rx(options.title_exclude_regex)
        if rx is not None and rx.search(row.get("title") or ""):
            return REASON_TITLE_EXCLUDE

    if options.language:
        text = " ".join(filter(None, [row.get("title"), row.get("about")]))
        detected = _detect_language(text)
        if detected != "unknown":
            wanted = options.language
            # "ru_or_en" пропускает ru, en и mixed; строгие "ru"/"en" — только совпадение.
            if wanted == "ru_or_en":
                if detected not in ("ru", "en", "mixed"):
                    return REASON_WRONG_LANGUAGE
            elif wanted == "ru":
                if detected not in ("ru", "mixed"):
                    return REASON_WRONG_LANGUAGE
            elif wanted == "en":
                if detected not in ("en", "mixed"):
                    return REASON_WRONG_LANGUAGE

    if not options.allow_noforwards and row.get("noforwards"):
        return REASON_NOFORWARDS

    slow = row.get("slowmode_seconds") or 0
    if options.min_slowmode_seconds is not None and slow < options.min_slowmode_seconds:
        return REASON_SLOWMODE_TOO_LOW
    if options.max_slowmode_seconds is not None and slow > options.max_slowmode_seconds:
        return REASON_SLOWMODE_TOO_HIGH

    return None
