"""Активные health-пробы аккаунта (PROJECT-STAGES §5.3, этап 4 УТП).

Каждая проба:
* принимает готовый ``TelegramClient`` (из ``ClientPool``);
* делает 1-2 лёгких вызова через :func:`around_telethon_call`
  (все health-ошибки автоматически попадают в ``health_events``);
* возвращает partial-payload для ``AccountHealth`` (dict, без побочек над БД).

Побочки над БД делает вызывающая задача — так пробы юнит-тестируемы через
подмену клиента без Postgres.

Спам-блок пробится только по требованию/после incident.spam_block (не в
периодическом cron): диалог с ``@SpamBot`` — реальное действие, лишний трафик
для «спящих» аккаунтов.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from telethon.errors import (
    AuthKeyUnregisteredError,
    PhoneNumberBannedError,
    SessionRevokedError,
    UserDeactivatedBanError,
    UserDeactivatedError,
)
from telethon.tl.functions.account import GetPasswordRequest
from telethon.tl.types import User

from core.queue.publisher import Publisher
from worker.health.monitor import around_telethon_call


SPAMBOT_USERNAME = "SpamBot"

# Маркеры ответов @SpamBot (RU/EN, устойчивые подстроки).
_SPAM_OK_MARKERS = (
    "Good news",
    "no limits",
    "хорошие новости",
    "нет никаких ограничений",
)
_SPAM_BLOCKED_MARKERS = (
    "limited",
    "ограничени",  # «ограничения», «ограничен»
)


async def probe_session(
    client: Any,
    *,
    account_id: int,
    session_factory: Any,
    publisher: Optional[Publisher] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Жива ли сессия: пробуем ``get_me()``.

    * успех → ``session_alive=True``, ``last_seen_alive_at=now``;
    * ``SessionRevoked/AuthKeyUnregistered/UserDeactivated*/PhoneNumberBanned``
      → монитор уже отфиксировал ban_detected; здесь возвращаем
      ``session_alive=False`` (и, для последней ошибки, ``phone_status=banned``);
    * прочие RPCError → инцидент/warning остаётся на мониторе, ``session_alive``
      трактуем как ``None`` (неизвестно) — не заражать snapshot ложным False.
    """
    now = now or datetime.now(timezone.utc)
    try:
        me = await around_telethon_call(
            lambda: client.get_me(),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            now=now,
        )
    except (
        AuthKeyUnregisteredError,
        SessionRevokedError,
        UserDeactivatedBanError,
        UserDeactivatedError,
    ):
        return {
            "session_alive": False,
            "last_session_check_at": now,
        }
    except PhoneNumberBannedError:
        return {
            "session_alive": False,
            "phone_status": "banned",
            "last_session_check_at": now,
            "last_phone_check_at": now,
        }
    except Exception:  # noqa: BLE001 — прочее не считаем «мёртвой» сессией
        return {"last_session_check_at": now}

    if not isinstance(me, User):
        return {"last_session_check_at": now}

    return {
        "session_alive": True,
        "last_seen_alive_at": now,
        "last_session_check_at": now,
    }


async def probe_profile(
    client: Any,
    *,
    account_id: int,
    session_factory: Any,
    publisher: Optional[Publisher] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Есть ли 2FA, username, avatar, bio.

    2FA определяем по ``GetPasswordRequest`` → ``has_password`` (не пытаемся
    ввести пароль). Остальные поля — из ``get_me()`` / ``get_entity(me)``.
    """
    now = now or datetime.now(timezone.utc)
    details: dict[str, Any] = {}

    try:
        me = await around_telethon_call(
            lambda: client.get_me(),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            now=now,
        )
    except Exception:  # noqa: BLE001 — на этой пробе не тревожим статус
        return {}

    if isinstance(me, User):
        details["has_username"] = bool(getattr(me, "username", None))
        details["has_avatar"] = getattr(me, "photo", None) is not None

    # bio живёт в full-user, тянем через get_entity(me).
    try:
        full = await around_telethon_call(
            lambda: client(GetPasswordRequest()),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            now=now,
        )
        details["has_2fa"] = bool(getattr(full, "has_password", False))
    except Exception:  # noqa: BLE001
        pass

    # bio — best-effort через get_entity(me); нет — пропускаем.
    try:
        entity = await around_telethon_call(
            lambda: client.get_entity("me"),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            now=now,
        )
        about = getattr(entity, "about", None)
        if about is not None:
            details["has_bio"] = bool(about.strip())
    except Exception:  # noqa: BLE001
        pass

    return details


async def probe_spamblock(
    client: Any,
    *,
    account_id: int,
    session_factory: Any,
    publisher: Optional[Publisher] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Спрашиваем ``@SpamBot`` о наличии ограничений.

    Диалог с реальным ботом → редкая операция (по требованию/после incident).
    Ответ парсим по устойчивым маркерам (RU/EN). Если не смогли распарсить —
    возвращаем только timestamp последней попытки, ``spam_blocked`` не трогаем.
    """
    now = now or datetime.now(timezone.utc)

    async def _dialog() -> str:
        entity = await client.get_entity(SPAMBOT_USERNAME)
        await client.send_message(entity, "/start")
        async for message in client.iter_messages(entity, limit=1):
            return getattr(message, "message", "") or ""
        return ""

    try:
        text = await around_telethon_call(
            _dialog,
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            now=now,
        )
    except Exception:  # noqa: BLE001
        return {"last_spam_check_at": now}

    lower = (text or "").lower()
    if any(m.lower() in lower for m in _SPAM_OK_MARKERS):
        return {
            "spam_blocked": False,
            "spam_until": None,
            "last_spam_check_at": now,
        }
    if any(m.lower() in lower for m in _SPAM_BLOCKED_MARKERS):
        return {
            "spam_blocked": True,
            "last_spam_check_at": now,
        }
    return {"last_spam_check_at": now}
