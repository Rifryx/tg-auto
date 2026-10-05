"""arq-хендлер parser_run — dispatch между chat_messages / chat_members.

Регистрируется под именем TaskName.PRIMING_PARSER_RUN
(имя историческое — сохранено, чтобы не менять enqueue-эндпоинты).
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from modules.parsing.parser.channel_commenters import parse_channel_commenters
from modules.parsing.parser.chat_members import parse_chat_members
from modules.parsing.parser.chat_messages import parse_chat_messages
from modules.parsing.parser.filters import FilterOptions
from modules.parsing.parser.post_reactors import parse_post_reactors

get_logger = structlog.get_logger


def _filter_options(payload: dict[str, Any]) -> FilterOptions:
    """Собирает FilterOptions из payload (Extraction+ фильтры)."""
    return FilterOptions(
        require_username=bool(payload.get("require_username", True)),
        premium_only=bool(payload.get("premium_only", False)),
        require_photo=bool(payload.get("require_photo", False)),
        verified_only=bool(payload.get("verified_only", False)),
        exclude_scam_fake=bool(payload.get("exclude_scam_fake", True)),
        require_phone_visible=bool(payload.get("require_phone_visible", False)),
        username_regex=payload.get("username_regex") or None,
        name_script=payload.get("name_script") or None,
        last_seen_max_days=(
            int(payload["last_seen_max_days"])
            if payload.get("last_seen_max_days") is not None
            else None
        ),
    )


async def parser_run(
    ctx: dict, kind: str, payload: dict[str, Any],
) -> Optional[dict]:
    """Точка входа arq для запуска парсинга.

    ``kind`` — chat_messages | chat_members | channel_commenters | post_reactors
    (см. API /modules/parsing/lists/run/*). ``payload`` — сериализованный запрос.
    """
    log = get_logger()

    filter_options = _filter_options(payload)

    if kind == "chat_messages":
        result = await parse_chat_messages(
            ctx,
            owner_user_id=int(payload["owner_user_id"]),
            name=str(payload["name"]),
            collector_account_id=int(payload["collector_account_id"]),
            chat_ref=str(payload["chat_ref"]),
            days_window=int(payload.get("days_window", 14)),
            min_messages=int(payload.get("min_messages", 1)),
            filter_options=filter_options,
        )
    elif kind == "chat_members":
        result = await parse_chat_members(
            ctx,
            owner_user_id=int(payload["owner_user_id"]),
            name=str(payload["name"]),
            collector_account_id=int(payload["collector_account_id"]),
            chat_ref=str(payload["chat_ref"]),
            only_recently_seen=bool(payload.get("only_recently_seen", True)),
            filter_options=filter_options,
        )
    elif kind == "channel_commenters":
        result = await parse_channel_commenters(
            ctx,
            owner_user_id=int(payload["owner_user_id"]),
            name=str(payload["name"]),
            collector_account_id=int(payload["collector_account_id"]),
            chat_ref=str(payload["chat_ref"]),
            days_window=int(payload.get("days_window", 14)),
            min_messages=int(payload.get("min_messages", 1)),
            filter_options=filter_options,
        )
    elif kind == "post_reactors":
        result = await parse_post_reactors(
            ctx,
            owner_user_id=int(payload["owner_user_id"]),
            name=str(payload["name"]),
            collector_account_id=int(payload["collector_account_id"]),
            chat_ref=str(payload["chat_ref"]),
            posts_limit=int(payload.get("posts_limit", 20)),
            reactions_per_post=int(payload.get("reactions_per_post", 100)),
            min_reactions=int(payload.get("min_reactions", 1)),
            filter_options=filter_options,
        )
    else:
        log.warning("parsing.parser_run.unknown_kind", kind=kind)
        return {"error": f"unknown kind {kind!r}"}

    if result is None:
        return {"skipped": True}
    return {
        "list_id": result.list_id,
        "raw_count": result.raw_count,
        "inserted": result.inserted,
        "filters_breakdown": result.filters_breakdown,
    }
