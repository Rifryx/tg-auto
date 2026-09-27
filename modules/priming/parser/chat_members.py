"""Парсер аудитории по списку участников чата (spec §8.1–8.2, промпт 3.2).

Использует ``channels.GetParticipants`` через ``client.iter_participants``
(Telethon сам пагинирует), собирает снимок пользователя, применяет
фильтры и вставляет цели.

Инварианты те же, что у ``chat_messages``:
* клиент — отдельный collector, через ClientPool;
* один governor.check_and_reserve на прогон (action_type "priming_parser");
* тексты и raw-объекты не хранятся — только идентификаторы и флаги
  фильтров.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from modules.priming.parser.filters import FilterOptions, apply_filters
from modules.priming.repositories import (
    BlacklistRepository,
    CampaignTargetRepository,
    TargetSourceRepository,
)
from modules.priming.schemas.enums import ParserSourceKind, TargetLastSeen

get_logger = structlog.get_logger

PARSER_ACTION_TYPE = "priming_parser"


@dataclass
class ParseResult:
    source_id: int
    raw_count: int
    inserted: int
    filters_breakdown: dict[str, int]


async def parse_chat_members(
    ctx: dict,
    *,
    campaign_id: int,
    collector_account_id: int,
    chat_ref: str,
    only_recently_seen: bool = True,
    filter_options: Optional[FilterOptions] = None,
) -> Optional[ParseResult]:
    log = get_logger()
    session_factory = ctx["session_factory"]
    pool = ctx["client_pool"]
    governor = ctx["governor"]

    if not await governor.check_and_reserve(
        collector_account_id, PARSER_ACTION_TYPE,
    ):
        log.info(
            "priming.parser.chat_members.rate_limited",
            collector_account_id=collector_account_id,
        )
        return None

    with session_factory() as session:
        source = TargetSourceRepository(session).create({
            "campaign_id": campaign_id,
            "kind": ParserSourceKind.CHAT_MEMBERS.value,
            "chat_ref": chat_ref,
        })
        source_id = source.id
        session.commit()

    client = await pool.get(collector_account_id)
    raw_rows: list[dict[str, Any]] = []
    try:
        entity = await client.get_entity(chat_ref)
        async for participant in client.iter_participants(entity):
            snap = _snapshot(participant)
            if only_recently_seen and snap["last_seen_bucket"] not in {
                TargetLastSeen.RECENTLY.value,
                TargetLastSeen.WITHIN_WEEK.value,
            }:
                # last_seen-фильтр применяем «на входе», чтобы не гонять
                # заведомо мёртвых через blacklist-lookup.
                continue
            raw_rows.append(snap)
    finally:
        await pool.release(collector_account_id)

    options = filter_options or FilterOptions()

    with session_factory() as session:
        blacklist_repo = (
            BlacklistRepository(session)
            if options.check_blacklist
            else None
        )
        outcome = apply_filters(
            raw_rows,
            options=options,
            blacklist_repo=blacklist_repo,
        )

        inserted = 0
        if outcome.kept:
            inserted = CampaignTargetRepository(session).bulk_create(
                campaign_id, [
                    {
                        "tg_user_id": r.get("tg_user_id"),
                        "username": r.get("username"),
                        "phone": r.get("phone"),
                        "has_premium": r.get("has_premium"),
                        "last_seen_bucket": r.get("last_seen_bucket") or TargetLastSeen.UNKNOWN.value,
                        "source_id": source_id,
                    }
                    for r in outcome.kept
                ],
            )
        breakdown_with_dedup = dict(outcome.breakdown)
        if len(outcome.kept) - inserted > 0:
            breakdown_with_dedup["already_in_campaign"] = (
                len(outcome.kept) - inserted
            )

        TargetSourceRepository(session).update(source_id, {
            "raw_count": len(raw_rows),
            "after_filters_count": inserted,
            "filters_breakdown": breakdown_with_dedup,
            "parsed_at": datetime.now(timezone.utc),
        })
        session.commit()

    log.info(
        "priming.parser.chat_members.done",
        campaign_id=campaign_id,
        source_id=source_id,
        raw=len(raw_rows),
        inserted=inserted,
        breakdown=breakdown_with_dedup,
    )
    return ParseResult(
        source_id=source_id,
        raw_count=len(raw_rows),
        inserted=inserted,
        filters_breakdown=breakdown_with_dedup,
    )


# ---------------------------------------------------------------------------


def _snapshot(user: Any) -> dict[str, Any]:
    """Лёгкий снимок Telethon User для фильтров + вставки."""
    return {
        "tg_user_id": getattr(user, "id", None),
        "username": getattr(user, "username", None),
        "phone": getattr(user, "phone", None),
        "has_premium": getattr(user, "premium", None),
        "is_bot": bool(getattr(user, "bot", False)),
        "is_deleted": bool(getattr(user, "deleted", False)),
        # is_admin — прокидывает вызывающая сторона, если ей это известно.
        "is_admin": bool(getattr(user, "is_admin", False)),
        "last_seen_bucket": _last_seen_bucket(getattr(user, "status", None)),
    }


def _last_seen_bucket(status: Any) -> str:
    """Маппинг ``UserStatus*`` из Telethon → :class:`TargetLastSeen`.

    Проверяем классы по имени, чтобы модуль не тянул тяжёлый импорт
    Telethon-типов (Telethon может отсутствовать в лёгких окружениях —
    парсер и тесты нашего фильтра всё равно работают на dict/SimpleNamespace).
    """
    if status is None:
        return TargetLastSeen.UNKNOWN.value
    name = type(status).__name__
    if name == "UserStatusOnline" or name == "UserStatusRecently":
        return TargetLastSeen.RECENTLY.value
    if name == "UserStatusLastWeek":
        return TargetLastSeen.WITHIN_WEEK.value
    if name == "UserStatusLastMonth":
        return TargetLastSeen.WITHIN_MONTH.value
    if name == "UserStatusEmpty" or name == "UserStatusOffline":
        return TargetLastSeen.LONG_AGO.value
    return TargetLastSeen.UNKNOWN.value
