"""Парсер реакторов на посты канала/чата (Extraction+, этап 1).

Берёт последние ``posts_limit`` постов, для каждого запрашивает список
поставивших реакции (``GetMessageReactionsListRequest``) и собирает уникальных
пользователей. ``min_reactions`` — порог «на скольких постах отметился».
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from telethon.tl.functions.messages import GetMessageReactionsListRequest

from modules.parsing.parser.chat_members import _snapshot
from modules.parsing.parser.chat_messages import ParseResult
from modules.parsing.parser.filters import FilterOptions, apply_filters
from modules.parsing.repositories import (
    ParsedListRepository,
    ParsedListTargetRepository,
)
from modules.priming.repositories import BlacklistRepository
from modules.priming.schemas.enums import ParserSourceKind, TargetLastSeen

get_logger = structlog.get_logger

PARSER_ACTION_TYPE = "priming_parser"


async def parse_post_reactors(
    ctx: dict,
    *,
    owner_user_id: int,
    name: str,
    collector_account_id: int,
    chat_ref: str,
    posts_limit: int = 20,
    reactions_per_post: int = 100,
    min_reactions: int = 1,
    filter_options: Optional[FilterOptions] = None,
) -> Optional[ParseResult]:
    log = get_logger()
    session_factory = ctx["session_factory"]
    pool = ctx["client_pool"]
    governor = ctx["governor"]
    now = ctx.get("now") or datetime.now(timezone.utc)

    if not await governor.check_and_reserve(collector_account_id, PARSER_ACTION_TYPE):
        log.info("parsing.post_reactors.rate_limited",
                 collector_account_id=collector_account_id)
        return None

    with session_factory() as session:
        parsed_list = ParsedListRepository(session).create({
            "owner_user_id": owner_user_id,
            "name": name,
            "source_kind": ParserSourceKind.POST_REACTORS.value,
            "chat_ref": chat_ref,
            "min_messages": min_reactions,
        })
        list_id = parsed_list.id
        session.commit()

    client = await pool.get(collector_account_id)
    # tg_user_id -> {"count": N, "snap": {...}}
    reactors: dict[int, dict[str, Any]] = {}
    try:
        entity = await client.get_entity(chat_ref)
        messages = await client.get_messages(entity, limit=posts_limit)
        for message in messages or []:
            msg_id = getattr(message, "id", None)
            if msg_id is None:
                continue
            try:
                res = await client(
                    GetMessageReactionsListRequest(
                        peer=entity, id=msg_id, limit=reactions_per_post
                    )
                )
            except Exception:  # noqa: BLE001 — у поста может не быть реакций / нет прав
                continue
            for user in getattr(res, "users", None) or []:
                uid = getattr(user, "id", None)
                if uid is None:
                    continue
                rec = reactors.get(int(uid))
                if rec is None:
                    reactors[int(uid)] = {"count": 1, "snap": _snapshot(user, now)}
                else:
                    rec["count"] += 1
    finally:
        await pool.release(collector_account_id)

    picked_rows: list[dict[str, Any]] = []
    below_min = 0
    for rec in reactors.values():
        if rec["count"] < min_reactions:
            below_min += 1
            continue
        picked_rows.append(rec["snap"])

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
        if below_min:
            breakdown["below_min_reactions"] = below_min
        already = len(outcome.kept) - inserted
        if already > 0:
            breakdown["already_in_list"] = already
        ParsedListRepository(session).update(list_id, {
            "raw_count": len(reactors),
            "after_filters_count": inserted,
            "filters_breakdown": breakdown,
            "parsed_at": datetime.now(timezone.utc),
        })
        session.commit()

    log.info("parsing.post_reactors.done", list_id=list_id,
             raw=len(reactors), inserted=inserted, breakdown=breakdown)
    return ParseResult(
        list_id=list_id, raw_count=len(reactors),
        inserted=inserted, filters_breakdown=breakdown,
    )
