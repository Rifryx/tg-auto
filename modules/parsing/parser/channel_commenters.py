"""Парсер комментаторов канала (Extraction+, этап 1).

Канал сам по себе не содержит участников — комментарии живут в его
*linked discussion chat*. Парсер резолвит канал → находит linked-чат →
собирает авторов сообщений за окно ``days_window`` (как chat_messages, но
источник — связанный чат канала).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from telethon.tl.functions.channels import GetFullChannelRequest

from modules.parsing.parser.chat_messages import ParseResult, _sender_snapshot, _to_utc
from modules.parsing.parser.filters import FilterOptions, apply_filters
from modules.parsing.repositories import (
    ParsedListRepository,
    ParsedListTargetRepository,
)
from modules.priming.repositories import BlacklistRepository
from modules.priming.schemas.enums import ParserSourceKind, TargetLastSeen

get_logger = structlog.get_logger

PARSER_ACTION_TYPE = "priming_parser"


async def parse_channel_commenters(
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

    if not await governor.check_and_reserve(collector_account_id, PARSER_ACTION_TYPE):
        log.info("parsing.channel_commenters.rate_limited",
                 collector_account_id=collector_account_id)
        return None

    with session_factory() as session:
        parsed_list = ParsedListRepository(session).create({
            "owner_user_id": owner_user_id,
            "name": name,
            "source_kind": ParserSourceKind.CHANNEL_COMMENTERS.value,
            "chat_ref": chat_ref,
            "days_window": days_window,
            "min_messages": min_messages,
        })
        list_id = parsed_list.id
        session.commit()

    client = await pool.get(collector_account_id)
    raw_senders: dict[int, dict[str, Any]] = {}
    linked_missing = False
    try:
        channel = await client.get_entity(chat_ref)
        full = await client(GetFullChannelRequest(channel=channel))
        linked_id = getattr(full.full_chat, "linked_chat_id", None)
        if not linked_id:
            linked_missing = True
        else:
            discussion = await client.get_entity(linked_id)
            min_dt = now - timedelta(days=days_window)
            async for message in client.iter_messages(discussion):
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
            "last_seen_days": None,
        })

    options = filter_options or FilterOptions()
    options.owner_user_id = owner_user_id

    with session_factory() as session:
        blacklist_repo = BlacklistRepository(session) if options.check_blacklist else None
        outcome = apply_filters(picked_rows, options=options, blacklist_repo=blacklist_repo)
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
        if linked_missing:
            breakdown["no_linked_chat"] = 1
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

    log.info("parsing.channel_commenters.done", list_id=list_id,
             raw=len(raw_senders), inserted=inserted, breakdown=breakdown)
    return ParseResult(
        list_id=list_id, raw_count=len(raw_senders),
        inserted=inserted, filters_breakdown=breakdown,
    )
