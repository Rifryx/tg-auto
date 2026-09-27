"""Парсер аудитории по сообщениям чата (spec §8.1, промпт 3.1).

Собирает id/username активных пользователей чата за последние ``days_window``
дней и оставляет тех, у кого не меньше ``min_messages`` сообщений.

Инварианты:
* читает через отдельный ``collector`` аккаунт (не тот, что будет
  праймить); открывается через ``worker.client_pool.ClientPool``;
* каждый вход в цикл iter_messages проходит через rate-limit governor
  (``priming_parser``);
* **не** хранит тексты сообщений — только счётчик и минимальные
  идентификаторы отправителей;
* результат складывается в БД как один ``PrimingTargetSource`` + N
  ``PrimingCampaignTarget`` со ``status=pending``; фильтры (username,
  premium, bots/deleted, blacklist) — на промпте 3.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

from modules.priming.repositories import (
    CampaignTargetRepository,
    TargetSourceRepository,
)
from modules.priming.schemas.enums import ParserSourceKind

get_logger = structlog.get_logger

PARSER_ACTION_TYPE = "priming_parser"


@dataclass
class ParseResult:
    """Компактный отчёт для job'а parser_run — публикуется в UI/logs."""

    source_id: int
    raw_count: int
    inserted: int


async def parse_chat_messages(
    ctx: dict,
    *,
    campaign_id: int,
    collector_account_id: int,
    chat_ref: str,
    days_window: int,
    min_messages: int = 1,
) -> Optional[ParseResult]:
    """Один прогон парсера. Пишет источник и вставляет цели.

    ``ctx`` — те же инъекции, что и у executor/orchestrator:
    ``session_factory``, ``client_pool``, ``governor`` (+ ``now``).
    """
    log = get_logger()
    session_factory = ctx["session_factory"]
    pool = ctx["client_pool"]
    governor = ctx["governor"]
    now = ctx.get("now") or datetime.now(timezone.utc)

    if not await governor.check_and_reserve(
        collector_account_id, PARSER_ACTION_TYPE
    ):
        log.info(
            "priming.parser.chat_messages.rate_limited",
            collector_account_id=collector_account_id,
        )
        return None

    # 1. Создаём source-запись сразу — UI/поллинг увидит job как queued.
    with session_factory() as session:
        source = TargetSourceRepository(session).create({
            "campaign_id": campaign_id,
            "kind": ParserSourceKind.CHAT_MESSAGES.value,
            "chat_ref": chat_ref,
            "days_window": days_window,
            "min_messages": min_messages,
        })
        source_id = source.id
        session.commit()

    # 2. Открываем клиента-парсера и стримим сообщения.
    client = await pool.get(collector_account_id)
    try:
        entity = await client.get_entity(chat_ref)
        min_dt = now - timedelta(days=days_window)
        raw_senders: dict[int, dict[str, Any]] = {}

        async for message in client.iter_messages(entity, offset_date=None):
            # Не даём алгоритму уйти глубже окна.
            msg_dt = getattr(message, "date", None)
            if msg_dt is not None and _to_utc(msg_dt) < min_dt:
                break
            sender_id = getattr(message, "sender_id", None)
            if sender_id is None:
                continue
            info = raw_senders.setdefault(int(sender_id), {"count": 0})
            info["count"] += 1
            # Заполняем лёгкий кэш — берём username/phone/premium с первого
            # попавшегося сообщения этого отправителя. Не тянем full user.
            sender = getattr(message, "sender", None)
            if sender is not None and "sender" not in info:
                info["sender"] = _sender_snapshot(sender)
    finally:
        await pool.release(collector_account_id)

    # 3. Отбираем по min_messages и сохраняем цели.
    picked_rows = []
    for sender_id, info in raw_senders.items():
        if info["count"] < min_messages:
            continue
        snap = info.get("sender") or {}
        picked_rows.append({
            "tg_user_id": sender_id,
            "username": snap.get("username"),
            "phone": snap.get("phone"),
            "has_premium": snap.get("premium"),
        })

    with session_factory() as session:
        inserted = 0
        if picked_rows:
            inserted = CampaignTargetRepository(session).bulk_create(
                campaign_id, picked_rows,
            )
        # after_filters_count == inserted; фильтры (username/premium/bots)
        # добавятся на промпте 3.2 — сейчас пропускаем всё, что прошло
        # min_messages.
        TargetSourceRepository(session).update(source_id, {
            "raw_count": len(raw_senders),
            "after_filters_count": inserted,
            "parsed_at": datetime.now(timezone.utc),
        })
        session.commit()

    log.info(
        "priming.parser.chat_messages.done",
        campaign_id=campaign_id,
        source_id=source_id,
        raw=len(raw_senders),
        inserted=inserted,
    )
    return ParseResult(
        source_id=source_id,
        raw_count=len(raw_senders),
        inserted=inserted,
    )


# ---------------------------------------------------------------------------


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _sender_snapshot(sender: Any) -> dict[str, Any]:
    """Снимок отправителя, безопасный к отсутствию полей у mock/user."""
    return {
        "username": getattr(sender, "username", None),
        "phone": getattr(sender, "phone", None),
        "premium": getattr(sender, "premium", None),
        "bot": getattr(sender, "bot", False),
        "deleted": getattr(sender, "deleted", False),
    }
