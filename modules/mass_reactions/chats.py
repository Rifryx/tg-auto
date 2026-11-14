"""Источник чатов масс-реакций: нормализация ввода и решение по подписке.

Чистая логика (без БД/Telethon) — нормализуем введённые ссылки/@username/id к
каноническому ``chat_ref`` и решаем итоговое состояние чата по факту подписки и
режиму уведомления. Используется и API (добавление по списку), и воркером
(после резолва/проверки подписки).
"""

from __future__ import annotations

import re
from typing import Optional

from modules.mass_reactions.schemas.enums import ChatNotifyMode, ChatState

_TME_RE = re.compile(r"(?:https?://)?(?:www\.)?t\.me/", re.IGNORECASE)
_INVITE_RE = re.compile(r"(?:t\.me/\+|t\.me/joinchat/|/\+)", re.IGNORECASE)


def normalize_chat_ref(raw: str) -> Optional[str]:
    """Канонический ключ чата из произвольного ввода. ``None`` — мусор/пусто.

    * ``-1001234`` / ``1001234`` → строка с id как есть;
    * invite-ссылка (``t.me/+…`` / ``t.me/joinchat/…``) → как есть, trim;
    * ``@name`` / ``t.me/name`` / ``name`` → голый lower-case username.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None

    if re.fullmatch(r"-?\d+", s):
        return s
    if _INVITE_RE.search(s):
        return s.rstrip("/")

    s = _TME_RE.sub("", s)
    s = s.lstrip("@")
    s = s.split("/")[0].split("?")[0].strip()
    if not s:
        return None
    return s.lower()


def parse_chat_list(text: str) -> list[str]:
    """Разбивает вставленный список (переносы/запятые/пробелы) → уникальные
    канонические chat_ref в порядке первого появления."""
    if not text:
        return []
    raw_parts = re.split(r"[\s,;]+", text)
    out: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        ref = normalize_chat_ref(part)
        if ref and ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def resolve_chat_state(*, subscribed: bool, notify_mode: str) -> str:
    """Итоговое состояние чата после резолва/проверки подписки.

    * подписан → ACTIVE (слушаем, реакции идут);
    * не подписан + notify_only → NOT_SUBSCRIBED (реакции не ставим);
    * не подписан + notify_and_join → JOINING (ставим задачу вступления).
    """
    if subscribed:
        return ChatState.ACTIVE.value
    if notify_mode == ChatNotifyMode.NOTIFY_AND_JOIN.value:
        return ChatState.JOINING.value
    return ChatState.NOT_SUBSCRIBED.value
