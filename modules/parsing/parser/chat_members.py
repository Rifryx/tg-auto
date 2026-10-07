"""Парсер по участникам чата (spec §8.2, промпт 3.2b).

Пишет в parsing.lists + parsing.list_targets.
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


async def parse_chat_members(
    ctx: dict,
    *,
    owner_user_id: int,
    name: str,
    collector_account_id: int,
    chat_ref: str,
    only_recently_seen: bool = True,
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
        log.info("parsing.chat_members.rate_limited",
                 collector_account_id=collector_account_id)
        return None

    with session_factory() as session:
        parsed_list = ParsedListRepository(session).create({
            "owner_user_id": owner_user_id,
            "name": name,
            "source_kind": ParserSourceKind.CHAT_MEMBERS.value,
            "chat_ref": chat_ref,
        })
        list_id = parsed_list.id
        session.commit()

    client = await pool.get(collector_account_id)
    raw_rows: list[dict[str, Any]] = []
    try:
        entity = await client.get_entity(chat_ref)
        async for participant in client.iter_participants(entity):
            snap = _snapshot(participant, now)
            if only_recently_seen and snap["last_seen_bucket"] not in {
                TargetLastSeen.RECENTLY.value,
                TargetLastSeen.WITHIN_WEEK.value,
            }:
                continue
            raw_rows.append(snap)
    finally:
        await pool.release(collector_account_id)

    options = filter_options or FilterOptions()
    options.owner_user_id = owner_user_id

    with session_factory() as session:
        blacklist_repo = (
            BlacklistRepository(session) if options.check_blacklist else None
        )
        outcome = apply_filters(
            raw_rows, options=options, blacklist_repo=blacklist_repo,
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
        already = len(outcome.kept) - inserted
        if already > 0:
            breakdown["already_in_list"] = already
        ParsedListRepository(session).update(list_id, {
            "raw_count": len(raw_rows),
            "after_filters_count": inserted,
            "filters_breakdown": breakdown,
            "parsed_at": datetime.now(timezone.utc),
        })
        session.commit()

    log.info(
        "parsing.chat_members.done", list_id=list_id,
        raw=len(raw_rows), inserted=inserted, breakdown=breakdown,
    )
    return ParseResult(
        list_id=list_id, raw_count=len(raw_rows),
        inserted=inserted, filters_breakdown=breakdown,
    )


def _snapshot(user: Any, now: datetime) -> dict[str, Any]:
    status = getattr(user, "status", None)
    return {
        "tg_user_id": getattr(user, "id", None),
        "username": getattr(user, "username", None),
        "phone": getattr(user, "phone", None),
        "has_premium": getattr(user, "premium", None),
        "is_bot": bool(getattr(user, "bot", False)),
        "is_deleted": bool(getattr(user, "deleted", False)),
        "is_admin": bool(getattr(user, "is_admin", False)),
        "is_verified": bool(getattr(user, "verified", False)),
        "is_scam": bool(getattr(user, "scam", False)),
        "is_fake": bool(getattr(user, "fake", False)),
        "has_photo": getattr(user, "photo", None) is not None,
        "first_name": getattr(user, "first_name", None),
        "last_name": getattr(user, "last_name", None),
        "last_seen_bucket": _last_seen_bucket(status),
        "last_seen_days": _last_seen_days(status, now),
    }


def _last_seen_days(status: Any, now: datetime) -> Optional[int]:
    """Приблизительное число дней с последнего онлайна (для точного фильтра)."""
    if status is None:
        return None
    name = type(status).__name__
    if name in {"UserStatusOnline", "UserStatusRecently"}:
        return 0
    if name == "UserStatusLastWeek":
        return 7
    if name == "UserStatusLastMonth":
        return 30
    if name == "UserStatusOffline":
        was = getattr(status, "was_online", None)
        if isinstance(was, datetime):
            delta = now - (was if was.tzinfo else was.replace(tzinfo=timezone.utc))
            return max(0, delta.days)
        return None
    return None


def _last_seen_bucket(status: Any) -> str:
    if status is None:
        return TargetLastSeen.UNKNOWN.value
    name = type(status).__name__
    if name in {"UserStatusOnline", "UserStatusRecently"}:
        return TargetLastSeen.RECENTLY.value
    if name == "UserStatusLastWeek":
        return TargetLastSeen.WITHIN_WEEK.value
    if name == "UserStatusLastMonth":
        return TargetLastSeen.WITHIN_MONTH.value
    if name in {"UserStatusEmpty", "UserStatusOffline"}:
        return TargetLastSeen.LONG_AGO.value
    return TargetLastSeen.UNKNOWN.value
