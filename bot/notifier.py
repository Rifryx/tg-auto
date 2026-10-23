"""Push-уведомления в Telegram-бота (этап 13b).

Слушает Redis pub/sub и рассылает форматированные сообщения администраторам
(``ADMIN_USER_IDS``). Одностраничный MVP: пока нет ownership колонки на
``accounts``, все уведомления идут админу — это single-tenant режим. Когда
появится ownership — здесь будет фильтр по user_id.

Слушаемые каналы:
* ``account_status`` — переходы состояния (retire, ban, cooldown).
* ``health.ban_risk_updated`` — рост риска бана.
* ``autopilot.events`` — сводка тика автопилота (что он сделал).

Фильтрация: не слать всё подряд, только важное:
* Ban / retire — всегда.
* Cooldown — всегда (может означать инцидент).
* Ban risk — только при переходе в HIGH/CRITICAL с MEDIUM/LOW.
* Autopilot — только если было ≥1 executed действие.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
from typing import Any, Optional

import redis.asyncio as aioredis
from aiogram import Bot

from core.config import get_settings

logger = logging.getLogger("bot.notifier")

_ACCOUNT_STATUS_CHANNEL = "account_status"
_BAN_RISK_CHANNEL = "health.ban_risk_updated"
_AUTOPILOT_CHANNEL = "autopilot.events"
_COMMENTING_ALERTS_CHANNEL = "commenting.alerts"
_SUPPORT_NEW_MESSAGE_CHANNEL = "support.new_message"


# Те же русские подписи статусов, что и в UI (frontend/src/shared/status.ts).
_STATUS_RU = {
    "created": "Создан",
    "warming": "Прогрев",
    "pool": "В пуле",
    "assigned": "В работе",
    "cooldown": "Пауза",
    "retired": "Выведен",
    "banned": "Бан",
}

_INITIATOR_RU = {
    "user": "вручную",
    "auto": "автоматически (автопилот)",
    "health": "по показателям здоровья",
}

# reason — это ``AccountEvent.value`` из core/state_machine/account.py.
_REASON_RU = {
    "account.created": "создание аккаунта",
    "warming.start": "начат прогрев",
    "warming.completed": "прогрев завершён",
    "container.attach": "назначен на задачу",
    "container.detach": "снят с задачи",
    "health.incident": "сбой/ошибка Telegram (flood/spam/бан прокси)",
    "cooldown.expired": "пауза закончилась",
    "account.retire": "ручной вывод",
    "account.restore": "возврат в пул",
    "health.ban_detected": "обнаружен бан",
    "account.acknowledge_ban": "бан подтверждён",
}


def _account_label(payload: dict[str, Any]) -> str:
    """«@username (+7999…, #64)» / «Имя (#64)» — по тому, что известно."""
    account_id = payload.get("account_id")
    username = payload.get("username")
    phone = payload.get("phone")
    display_name = payload.get("display_name")
    primary = f"@{username}" if username else (display_name or phone or f"#{account_id}")
    extra = phone if phone and primary != phone else None
    tail = f" ({extra}, #{account_id})" if extra else f" (#{account_id})"
    return html.escape(f"{primary}{tail}")


def _fmt_account_status(payload: dict[str, Any]) -> Optional[str]:
    """Форматирует событие статуса; None — если событие не важно."""
    from_status = payload.get("from")
    to_status = payload.get("to")
    initiator = payload.get("initiator", "auto")
    who = _account_label(payload)
    reason = _REASON_RU.get(payload.get("reason") or "", payload.get("reason") or "—")
    from_ru = _STATUS_RU.get(from_status or "", from_status or "—")
    initiator_ru = _INITIATOR_RU.get(initiator, initiator)

    # Важные переходы: banned, retired, cooldown.
    if to_status == "banned":
        return (
            f"🚫 <b>Аккаунт {who} забанен</b>\n"
            f"Причина: {reason}\n"
            f"Инициатор: {initiator_ru}"
        )
    if to_status == "retired" and initiator != "user":
        return (
            f"⚠️ <b>Аккаунт {who} выведен из работы</b>\n"
            f"Был в статусе «{from_ru}», инициатор: {initiator_ru}\n"
            f"Причина: {reason}"
        )
    if to_status == "cooldown":
        lines = [
            f"❄️ <b>Аккаунт {who} на охлаждении</b>",
            f"Пришёл из статуса «{from_ru}»",
            f"Причина: {reason}",
        ]
        until = _fmt_until(payload.get("cooldown_until"))
        if until:
            lines.append(f"До: {until}")
        return "\n".join(lines)
    return None


def _fmt_until(raw: Optional[str]) -> Optional[str]:
    """ISO-таймстамп cooldown_until → «22.10 23:40 UTC» для читаемости в чате."""
    if not raw:
        return None
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return dt.strftime("%d.%m %H:%M UTC")


def _fmt_ban_risk(payload: dict[str, Any]) -> Optional[str]:
    """Форматирует событие роста риска; None — если не важно."""
    account_id = payload.get("account_id")
    score = payload.get("risk_score")
    level = payload.get("risk_level")
    previous = payload.get("previous_risk_score")

    # Только при повышении в HIGH или CRITICAL. Стабильный высокий не спамим.
    if level not in ("high", "critical"):
        return None
    # previous None означает первый расчёт — если уровень уже HIGH+, шлём.
    # Иначе шлём только если оценка выросла (иначе спам).
    if previous is not None and previous >= score:
        return None

    emoji = "🔴" if level == "critical" else "🟠"
    prev_str = f"{round((previous or 0) * 100)}→" if previous is not None else ""
    return (
        f"{emoji} <b>Риск бана вырос</b>\n"
        f"Аккаунт: <code>#{account_id}</code>\n"
        f"Оценка: {prev_str}<b>{round(score * 100)}/100</b> "
        f"(<code>{level}</code>)"
    )


def _fmt_autopilot(payload: dict[str, Any]) -> Optional[str]:
    """Сводка тика автопилота; None — если ничего не сделано."""
    executed = payload.get("executed", 0)
    if not executed:
        return None
    by_type = payload.get("by_type", {})
    lines = [f"🤖 <b>Автопилот: {executed} действий</b>"]
    for action_type, count in by_type.items():
        pretty = {
            "start_warming": "Запуск прогрева",
            "retire_risky": "Ретайр рискованного",
            "throttle": "Снижение темпа",
        }.get(action_type, action_type)
        lines.append(f"• {pretty}: <code>{count}</code>")
    return "\n".join(lines)


_CHANNEL_ALERT_TITLE = {
    "not_subscribed": "📭 <b>Аккаунт #{account} не подписан на канал</b>",
    "auto_subscribed": "✅ <b>Аккаунт #{account} подписан на канал автоматически</b>",
    "access_lost": "⛔ <b>Аккаунт #{account} потерял доступ к обсуждению</b>",
    "blacklisted": "🚫 <b>Канал добавлен в чёрный список кампании</b>",
    # Verify-after-post (E4.2): коммент аккаунта пропал из чата.
    "comment_removed": "🗑 <b>Модератор снял коммент аккаунта #{account}</b>",
}


def _fmt_commenting_alert(payload: dict[str, Any]) -> Optional[str]:
    """Алерт нейрокомментинга: E3.2 (каналы) и E4.2 (verify_after_post)."""
    title = _CHANNEL_ALERT_TITLE.get(payload.get("kind") or "")
    if title is None:
        return None
    # Ссылку и детали вводит пользователь — экранируем под parse_mode=HTML.
    lines = [title.format(account=payload.get("account_id"))]
    channel = payload.get("channel")
    if channel:
        lines.append(f"Канал: <code>{html.escape(str(channel))}</code>")
    if payload.get("campaign_id") is not None:
        lines.append(f"Кампания: <code>#{payload['campaign_id']}</code>")
    if payload.get("posted_message_id") is not None:
        lines.append(f"Сообщение: <code>#{payload['posted_message_id']}</code>")
    if payload.get("detail"):
        lines.append(html.escape(str(payload["detail"])))
    return "\n".join(lines)


_HANDLERS = {
    _ACCOUNT_STATUS_CHANNEL: _fmt_account_status,
    _BAN_RISK_CHANNEL: _fmt_ban_risk,
    _AUTOPILOT_CHANNEL: _fmt_autopilot,
    _COMMENTING_ALERTS_CHANNEL: _fmt_commenting_alert,
}


async def _send_to_all(bot: Bot, chat_ids: list[str], text: str) -> None:
    """Разослать сообщение всем указанным chat_id. Ошибки не роняют цикл."""
    for chat_id in chat_ids:
        try:
            await bot.send_message(int(chat_id), text, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "bot.notifier.send_failed chat_id=%s: %r", chat_id, exc
            )


async def _handle_support_new_message(
    bot: Bot, payload: dict[str, Any], admin_ids: list[str]
) -> None:
    """Пересылает обращение в поддержку менеджерам (админам) и запоминает связку
    «сообщение бота → user_id», чтобы ответ реплаем вернулся нужному человеку."""
    from api.deps.db import _session_factory
    from core.repositories.support import SupportRepository

    user_id = str(payload.get("user_id") or "")
    username = payload.get("username")
    text = str(payload.get("text") or "")
    if not user_id or not text:
        return
    who = f"@{username}" if username else f"id {user_id}"
    body = (
        f"💬 <b>Поддержка от {html.escape(who)}</b>\n"
        f"user_id: <code>{html.escape(user_id)}</code>\n\n"
        f"{html.escape(text)}\n\n"
        f"<i>Ответьте реплаем на это сообщение — ответ придёт пользователю.</i>"
    )
    for chat_id in admin_ids:
        try:
            sent = await bot.send_message(int(chat_id), body, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            logger.warning("bot.support.forward_failed chat_id=%s: %r", chat_id, exc)
            continue
        try:
            with _session_factory()() as session:
                SupportRepository(session).add_relay(
                    chat_id=str(chat_id),
                    message_id=int(sent.message_id),
                    user_id=user_id,
                )
                session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("bot.support.relay_store_failed: %r", exc)


async def run_notifier(bot: Bot) -> None:
    """Фоновая задача-слушатель. Пришедшие события форматирует и рассылает."""
    settings = get_settings()
    if not settings.admin_ids:
        logger.warning(
            "bot.notifier: ADMIN_USER_IDS пуст — пуши слать некому, тихо стою"
        )
        # Всё равно подписываемся: чтобы включение ADMIN_USER_IDS без рестарта
        # не работало — но и не тратим коннекты впустую.
        return

    redis = aioredis.from_url(settings.redis_url)
    pubsub = redis.pubsub()
    await pubsub.subscribe(*_HANDLERS.keys(), _SUPPORT_NEW_MESSAGE_CHANNEL)
    logger.info(
        "bot.notifier.started admins=%d channels=%s",
        len(settings.admin_ids),
        list(_HANDLERS.keys()),
    )
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            channel = message.get("channel")
            if isinstance(channel, (bytes, bytearray)):
                channel = channel.decode()
            raw = message.get("data")
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode()
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue

            # Поддержка: особый путь — пересылаем менеджерам + пишем релей.
            if channel == _SUPPORT_NEW_MESSAGE_CHANNEL:
                await _handle_support_new_message(
                    bot, payload, list(settings.admin_ids)
                )
                continue

            handler = _HANDLERS.get(channel)
            if handler is None:
                continue
            text = handler(payload)
            if not text:
                continue
            await _send_to_all(bot, list(settings.admin_ids), text)
    finally:
        try:
            await pubsub.aclose()
        finally:
            await redis.aclose()
