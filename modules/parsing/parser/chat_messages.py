"""Парсер по сообщениям чата (spec §8.1, промпт 3.2b).

Пишет в parsing.lists + parsing.list_targets (не в priming). Прайминг
получает готовый список через отдельный endpoint import-list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

from modules.parsing.parser.filters import FilterOptions, apply_filters
from modules.parsing.repositories import (
    ParsedListRepository,
    ParsedListTargetRepository,
)
from modules.priming.repositories import BlacklistRepository
from modules.priming.schemas.enums import ParserSourceKind, TargetLastSeen

get_logger = structlog.get_logger

PARSER_ACTION_TYPE = "priming_parser"


@dataclass
class ParseResult:
    list_id: int
    raw_count: int
    inserted: int
    filters_breakdown: dict[str, int]


async def parse_chat_messages(
    ctx: dict,
    *,
    owner_user_id: int,
    name: str,
    collector_account_id: int,
    chat_ref: str,
    days_window: int,
    min_messages: int = 1,
    filter_options: Optional[FilterOptions] = None,
) -> Optional[ParseResult]:
    log = get_logger()
    session_factory = ctx["session_factory"]
    pool = ctx["client_pool"]
    governor = ctx["governor"]
    now = ctx.get("now") or datetime.now(timezone.utc)

    if not await governor.check_and_reserve(
        collector_account_id, PARSER_ACTION_TYPE,
    ):
        log.info("parsing.chat_messages.rate_limited",
                 collector_account_id=collector_account_id)
        return None

    # 1. Создаём список — UI-поллинг сразу увидит job.
    with session_factory() as session:
        parsed_list = ParsedListRepository(session).create({
            "owner_user_id": owner_user_id,
            "name": name,
            "source_kind": ParserSourceKind.CHAT_MESSAGES.value,
            "chat_ref": chat_ref,
            "days_window": days_window,
            "min_messages": min_messages,
        })
        list_id = parsed_list.id
        session.commit()

    # 2. Читаем чат.
    client = await pool.get(collector_account_id)
    try:
        entity = await client.get_entity(chat_ref)
        min_dt = now - timedelta(days=days_window)
        raw_senders: dict[int, dict[str, Any]] = {}
        async for message in client.iter_messages(entity, offset_date=None):
            msg_dt = getattr(message, "date", None)
            if msg_dt is not None and _to_utc(msg_dt) < min_dt:
                break
            sender_id = getattr(message, "sender_id", None)
            if sender_id is None:
                continue
            info = raw_senders.setdefault(int(sender_id), {"count": 0})
            info["count"] += 1
            sender = getattr(message, "sender", None)
            if sender is not None and "sender" not in info:
                info["sender"] = _sender_snapshot(sender)
    finally:
        await pool.release(collector_account_id)

    # 3. Отбор + фильтры.
    picked_rows: list[dict[str, Any]] = []
    below_min = 0
    for sender_id, info in raw_senders.items():
        if info["count"] < min_messages:
            below_min += 1
            continue
        snap = info.get("sender") or {}
        picked_rows.append({
            "tg_user_id": sender_id,
            "username": snap.get("username"),
            "phone": snap.get("phone"),
            "has_premium": snap.get("premium"),
            "is_bot": bool(snap.get("bot", False)),
            "is_deleted": bool(snap.get("deleted", False)),
            "is_admin": False,
            "is_verified": bool(snap.get("verified", False)),
            "is_scam": bool(snap.get("scam", False)),
            "is_fake": bool(snap.get("fake", False)),
            "has_photo": bool(snap.get("has_photo", False)),
            "first_name": snap.get("first_name"),
            "last_name": snap.get("last_name"),
            "last_seen_bucket": TargetLastSeen.UNKNOWN.value,
            "last_seen_days": None,  # из сообщений статус недоступен
        })

    options = filter_options or FilterOptions()
    options.owner_user_id = owner_user_id

    with session_factory() as session:
        blacklist_repo = (
            BlacklistRepository(session) if options.check_blacklist else None
        )
        outcome = apply_filters(
            picked_rows, options=options, blacklist_repo=blacklist_repo,
        )
        inserted = 0
        if outcome.kept:
            inserted = ParsedListTargetRepository(session).bulk_create(
                list_id,
                [
                    {
                        "tg_user_id": r.get("tg_user_id"),
                        "username": r.get("username"),
                        "phone": r.get("phone"),
                        "has_premium": r.get("has_premium"),
                        "last_seen_bucket": r.get("last_seen_bucket") or TargetLastSeen.UNKNOWN.value,
                    }
                    for r in outcome.kept
                ],
            )
        breakdown = dict(outcome.breakdown)
        if below_min:
            breakdown["below_min_messages"] = below_min
        already = len(outcome.kept) - inserted
        if already > 0:
            breakdown["already_in_list"] = already

        ParsedListRepository(session).update(list_id, {
            "raw_count": len(raw_senders),
            "after_filters_count": inserted,
            "filters_breakdown": breakdown,
            "parsed_at": datetime.now(timezone.utc),
        })
        session.commit()

    log.info(
        "parsing.chat_messages.done", list_id=list_id,
        raw=len(raw_senders), inserted=inserted, breakdown=breakdown,
    )
    return ParseResult(
        list_id=list_id, raw_count=len(raw_senders),
        inserted=inserted, filters_breakdown=breakdown,
    )


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _sender_snapshot(sender: Any) -> dict[str, Any]:
    return {
        "username": getattr(sender, "username", None),
        "phone": getattr(sender, "phone", None),
        "premium": getattr(sender, "premium", None),
        "bot": getattr(sender, "bot", False),
        "deleted": getattr(sender, "deleted", False),
        "verified": getattr(sender, "verified", False),
        "scam": getattr(sender, "scam", False),
        "fake": getattr(sender, "fake", False),
        "has_photo": getattr(sender, "photo", None) is not None,
        "first_name": getattr(sender, "first_name", None),
        "last_name": getattr(sender, "last_name", None),
    }
