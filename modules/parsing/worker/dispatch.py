"""arq-хендлер parser_run — dispatch между chat_messages / chat_members.

Регистрируется под именем TaskName.PRIMING_PARSER_RUN
(имя историческое — сохранено, чтобы не менять enqueue-эндпоинты).
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from modules.parsing.parser.chat_members import parse_chat_members
from modules.parsing.parser.chat_messages import parse_chat_messages
from modules.parsing.parser.filters import FilterOptions

get_logger = structlog.get_logger


async def parser_run(
    ctx: dict, kind: str, payload: dict[str, Any],
) -> Optional[dict]:
    """Точка входа arq для запуска парсинга.

    ``kind`` — ``chat_messages`` | ``chat_members`` (см. API эндпоинты
    /modules/parsing/lists/run/*). ``payload`` — сериализованный запрос.
    """
    log = get_logger()

    filter_options = FilterOptions(
        require_username=bool(payload.get("require_username", True)),
        premium_only=bool(payload.get("premium_only", False)),
    )

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
