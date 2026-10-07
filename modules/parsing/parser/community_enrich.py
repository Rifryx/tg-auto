"""Обогащение сообществ (каналов/чатов) collector-аккаунтом (Discovery, этап 2).

Нативный Telegram не умеет искать сообщества по теме/подписчикам — но умеет
по известной ссылке отдать живую инфу. Парсер принимает список ссылок/@, по
каждой резолвит канал/чат, собирает: участников, linked-чат, дату последнего
поста, тип, verified/scam/fake, slow-mode — и фильтрует набор.

Публичные ссылки (@/t.me/name) обогащаются полностью. Инвайты (t.me/+hash)
дают ограниченную инфу через CheckChatInvite (без вступления). Папки-addlist
в этом этапе не разворачиваются (reason='folder_unsupported').
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import CheckChatInviteRequest

from modules.parsing.parser.community_filters import (
    CommunityFilterOptions,
    first_community_drop_reason,
)
from modules.parsing.repositories import (
    ParsedCommunityItemRepository,
    ParsedListRepository,
)
from modules.priming.schemas.enums import ParserSourceKind
from worker.telegram_refs import classify_ref, invite_hash, public_ref

get_logger = structlog.get_logger

PARSER_ACTION_TYPE = "priming_parser"


@dataclass
class CommunityParseResult:
    list_id: int
    raw_count: int
    inserted: int
    filters_breakdown: dict[str, int]


async def enrich_communities(
    ctx: dict,
    *,
    owner_user_id: int,
    name: str,
    collector_account_id: int,
    refs: list[str],
    filter_options: Optional[CommunityFilterOptions] = None,
) -> Optional[CommunityParseResult]:
    log = get_logger()
    session_factory = ctx["session_factory"]
    pool = ctx["client_pool"]
    governor = ctx["governor"]
    now = ctx.get("now") or datetime.now(timezone.utc)
    options = filter_options or CommunityFilterOptions()

    if not await governor.check_and_reserve(collector_account_id, PARSER_ACTION_TYPE):
        log.info("parsing.community_enrich.rate_limited",
                 collector_account_id=collector_account_id)
        return None

    with session_factory() as session:
        parsed_list = ParsedListRepository(session).create({
            "owner_user_id": owner_user_id,
            "name": name,
            "source_kind": ParserSourceKind.COMMUNITY_ENRICH.value,
        })
        list_id = parsed_list.id
        session.commit()

    client = await pool.get(collector_account_id)
    rows: list[dict[str, Any]] = []
    breakdown: dict[str, int] = {}

    def _drop(reason: str) -> None:
        breakdown[reason] = breakdown.get(reason, 0) + 1

    try:
        for raw in refs:
            kind = classify_ref(raw)
            try:
                if kind == "folder":
                    _drop("folder_unsupported")
                    continue
                if kind == "invite":
                    snap = await _snapshot_invite(client, raw, now)
                else:
                    snap = await _snapshot_public(client, raw, now)
            except Exception as exc:  # noqa: BLE001 — недоступный/битый ref
                _drop("resolve_failed")
                log.info("parsing.community_enrich.resolve_failed", ref=raw, error=repr(exc))
                continue
            if snap is None:
                _drop("resolve_failed")
                continue
            reason = first_community_drop_reason(snap, options)
            if reason is not None:
                _drop(reason)
                continue
            rows.append(snap)
    finally:
        await pool.release(collector_account_id)

    with session_factory() as session:
        inserted = 0
        if rows:
            inserted = ParsedCommunityItemRepository(session).bulk_create(
                list_id, [_to_item(r) for r in rows]
            )
        already = len(rows) - inserted
        if already > 0:
            breakdown["already_in_list"] = already
        ParsedListRepository(session).update(list_id, {
            "raw_count": len(refs),
            "after_filters_count": inserted,
            "filters_breakdown": breakdown,
            "parsed_at": datetime.now(timezone.utc),
        })
        session.commit()

    log.info("parsing.community_enrich.done", list_id=list_id,
             raw=len(refs), inserted=inserted, breakdown=breakdown)
    return CommunityParseResult(
        list_id=list_id, raw_count=len(refs),
        inserted=inserted, filters_breakdown=breakdown,
    )


async def _snapshot_public(client, raw: str, now: datetime) -> Optional[dict]:
    entity = await client.get_entity(public_ref(raw))
    return await snapshot_from_entity(client, entity, now, input_ref=raw)


async def snapshot_from_entity(
    client, entity, now: datetime, *, input_ref: str
) -> Optional[dict]:
    """Строит community-снапшот из уже резолвленной сущности (канал/чат).

    Переиспользуется discovery-движком (у него сущности уже на руках после
    поиска/рекомендаций — не нужно повторно резолвить по ссылке)."""
    is_megagroup = bool(getattr(entity, "megagroup", False))
    kind = "chat" if is_megagroup else "channel"
    username = getattr(entity, "username", None)

    participants = getattr(entity, "participants_count", None)
    linked_chat_id = None
    slowmode = None
    about = None
    try:
        full = await client(GetFullChannelRequest(channel=entity))
        fc = full.full_chat
        participants = getattr(fc, "participants_count", None) or participants
        linked_chat_id = getattr(fc, "linked_chat_id", None)
        slowmode = getattr(fc, "slowmode_seconds", None)
        about = getattr(fc, "about", None)
    except Exception:  # noqa: BLE001 — не критично, работаем с entity-инфо
        pass

    last_post_days = None
    last_post_at = None
    try:
        msgs = await client.get_messages(entity, limit=1)
        if msgs:
            d = getattr(msgs[0], "date", None)
            if isinstance(d, datetime):
                last_post_at = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
                last_post_days = max(0, (now - last_post_at).days)
    except Exception:  # noqa: BLE001
        pass

    return {
        "input_ref": input_ref,
        "channel_tg_id": getattr(entity, "id", None),
        "access_hash": getattr(entity, "access_hash", None),
        "title": getattr(entity, "title", None),
        "username": username,
        "is_public": username is not None,
        "kind": kind,
        "participants_count": participants,
        "has_linked_chat": linked_chat_id is not None,
        "linked_chat_id": linked_chat_id,
        "last_post_days": last_post_days,
        "last_post_at": last_post_at,
        "is_verified": bool(getattr(entity, "verified", False)),
        "is_scam": bool(getattr(entity, "scam", False)),
        "is_fake": bool(getattr(entity, "fake", False)),
        "slowmode_seconds": slowmode,
        "about": about,
    }


async def _snapshot_invite(client, raw: str, now: datetime) -> Optional[dict]:
    h = invite_hash(raw)
    if not h:
        return None
    res = await client(CheckChatInviteRequest(hash=h))
    chat = getattr(res, "chat", None)  # ChatInviteAlready/Peek — уже есть чат
    if chat is not None:
        is_megagroup = bool(getattr(chat, "megagroup", False))
        return {
            "input_ref": raw,
            "channel_tg_id": getattr(chat, "id", None),
            "access_hash": getattr(chat, "access_hash", None),
            "title": getattr(chat, "title", None),
            "username": getattr(chat, "username", None),
            "is_public": getattr(chat, "username", None) is not None,
            "kind": "chat" if is_megagroup else "channel",
            "participants_count": getattr(chat, "participants_count", None),
            "has_linked_chat": False,
            "linked_chat_id": None,
            "last_post_days": None,
            "is_verified": bool(getattr(chat, "verified", False)),
            "is_scam": bool(getattr(chat, "scam", False)),
            "is_fake": bool(getattr(chat, "fake", False)),
            "slowmode_seconds": None,
            "about": None,
        }
    # ChatInvite (ещё не вступили) — ограниченная инфа.
    is_megagroup = bool(getattr(res, "megagroup", False))
    is_broadcast = bool(getattr(res, "broadcast", False))
    return {
        "input_ref": raw,
        "channel_tg_id": None,
        "access_hash": None,
        "title": getattr(res, "title", None),
        "username": None,
        "is_public": False,
        "kind": "channel" if is_broadcast and not is_megagroup else "chat",
        "participants_count": getattr(res, "participants_count", None),
        "has_linked_chat": False,
        "linked_chat_id": None,
        "last_post_days": None,
        "is_verified": bool(getattr(res, "verified", False)),
        "is_scam": bool(getattr(res, "scam", False)),
        "is_fake": bool(getattr(res, "fake", False)),
        "slowmode_seconds": None,
        "about": getattr(res, "about", None),
    }


def _to_item(snap: dict) -> dict:
    """Снапшот → поля community_items (last_post_days → last_post_at не пишем:
    храним только то, что в таблице; days — лишь для фильтра)."""
    item = {k: v for k, v in snap.items() if k != "last_post_days"}
    return item
