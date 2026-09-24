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


def _fmt_account_status(payload: dict[str, Any]) -> Optional[str]:
    """Форматирует событие статуса; None — если событие не важно."""
    from_status = payload.get("from")
    to_status = payload.get("to")
    account_id = payload.get("account_id")
    initiator = payload.get("initiator", "auto")

    # Важные переходы: banned, retired, cooldown.
    if to_status == "banned":
        return (
            f"🚫 <b>Аккаунт #{account_id} забанен</b>\n"
            f"Инициатор: <code>{initiator}</code>"
        )
    if to_status == "retired" and initiator != "user":
        return (
            f"⚠️ <b>Аккаунт #{account_id} выведен из работы</b>\n"
            f"Из <code>{from_status}</code> инициатор <code>{initiator}</code>"
        )
    if to_status == "cooldown":
        return (
            f"❄️ <b>Аккаунт #{account_id} на охлаждении</b>\n"
            f"Пришёл из <code>{from_status}</code>"
        )
    return None


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
    await pubsub.subscribe(*_HANDLERS.keys())
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
