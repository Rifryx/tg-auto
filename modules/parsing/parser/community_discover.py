"""Бесплатный нативный discovery сообществ (каналы/чаты) — без внешних сервисов.

Собирает кандидатов СВОИМ collector-аккаунтом:
* ``use_search`` — глобальный поиск Telegram по ключевику (``contacts.Search``);
* ``use_recommendations`` — «похожие каналы» (ML-рекомендации Telegram,
  ``GetChannelRecommendations``) с BFS-расширением на глубину ``depth``;
* ``use_forwards`` — каналы, откуда сиды репостят (``message.fwd_from``);
* ``use_mentions`` — @/t.me-ссылки из постов сидов.

Найденные сущности обогащаются (``snapshot_from_entity``) и фильтруются теми же
community-критериями, что и ``community_enrich``. Результат — в
``parsing.community_items`` (source_kind ``community_enrich``).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from telethon.tl.functions.channels import GetChannelRecommendationsRequest
from telethon.tl.functions.contacts import SearchRequest as ContactsSearch
from telethon.tl.types import PeerChannel

from modules.parsing.parser.community_enrich import (
    CommunityParseResult,
    _to_item,
    snapshot_from_entity,
)
from modules.parsing.parser.community_filters import (
    CommunityFilterOptions,
    first_community_drop_reason,
)
from modules.parsing.repositories import (
    ParsedCommunityItemRepository,
    ParsedListRepository,
)
from modules.priming.schemas.enums import ParserSourceKind
from worker.telegram_refs import public_ref

get_logger = structlog.get_logger

PARSER_ACTION_TYPE = "priming_parser"

_MENTION_RE = re.compile(r"(?:@|t\.me/)([A-Za-z0-9_]{4,32})")
_MSG_SCAN_LIMIT = 200  # сколько постов сида сканировать для forwards/mentions


async def discover_communities(
    ctx: dict,
    *,
    owner_user_id: int,
    name: str,
    collector_account_id: int,
    seeds: list[str],
    term: Optional[str] = None,
    use_search: bool = True,
    use_recommendations: bool = True,
    use_forwards: bool = False,
    use_mentions: bool = False,
    depth: int = 2,
    max_results: int = 200,
    filter_options: Optional[CommunityFilterOptions] = None,
) -> Optional[CommunityParseResult]:
    log = get_logger()
    session_factory = ctx["session_factory"]
    pool = ctx["client_pool"]
    governor = ctx["governor"]
    now = ctx.get("now") or datetime.now(timezone.utc)
    options = filter_options or CommunityFilterOptions()

    if not await governor.check_and_reserve(collector_account_id, PARSER_ACTION_TYPE):
        log.info("parsing.discover.rate_limited", collector_account_id=collector_account_id)
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
    breakdown: dict[str, int] = {}

    def _drop(reason: str) -> None:
        breakdown[reason] = breakdown.get(reason, 0) + 1

    # candidates: channel_id -> entity (сущности из поиска/рекомендаций уже
    # пригодны для снапшота, повторный resolve не нужен).
    candidates: dict[int, Any] = {}

    def _add(entity: Any) -> bool:
        if getattr(entity, "title", None) is None:  # не канал/чат (напр. user)
            return False
        cid = getattr(entity, "id", None)
        if cid is None or cid in candidates:
            return False
        candidates[int(cid)] = entity
        return len(candidates) < max_results

    try:
        seed_entities: list[Any] = []
        for raw in seeds:
            try:
                ent = await client.get_entity(public_ref(raw))
                seed_entities.append(ent)
                _add(ent)
            except Exception:  # noqa: BLE001
                _drop("seed_resolve_failed")

        # 1) Глобальный поиск по ключевику.
        if use_search and term and len(candidates) < max_results:
            try:
                res = await client(ContactsSearch(q=term, limit=min(max_results, 100)))
                for ch in getattr(res, "chats", None) or []:
                    if not _add(ch):
                        break
            except Exception as exc:  # noqa: BLE001
                log.info("parsing.discover.search_failed", error=repr(exc))

        # 2) «Похожие каналы» — BFS по рекомендациям на глубину depth.
        if use_recommendations:
            frontier = list(seed_entities)
            for _ in range(depth):
                if len(candidates) >= max_results or not frontier:
                    break
                next_frontier: list[Any] = []
                for ent in frontier:
                    if len(candidates) >= max_results:
                        break
                    try:
                        rec = await client(GetChannelRecommendationsRequest(channel=ent))
                    except Exception:  # noqa: BLE001
                        continue
                    for ch in getattr(rec, "chats", None) or []:
                        was_new = int(getattr(ch, "id", -1)) not in candidates
                        if not _add(ch):
                            break
                        if was_new and not getattr(ch, "megagroup", False):
                            next_frontier.append(ch)
                frontier = next_frontier

        # 3) Форварды и упоминания из постов сидов (опц., дороже).
        if (use_forwards or use_mentions) and seed_entities:
            for seed in seed_entities:
                if len(candidates) >= max_results:
                    break
                try:
                    async for msg in client.iter_messages(seed, limit=_MSG_SCAN_LIMIT):
                        if len(candidates) >= max_results:
                            break
                        if use_forwards:
                            fwd = getattr(msg, "fwd_from", None)
                            frm = getattr(fwd, "from_id", None) if fwd else None
                            if isinstance(frm, PeerChannel):
                                await _try_add_by_peer(client, frm, _add, _drop)
                        if use_mentions and getattr(msg, "message", None):
                            for uname in set(_MENTION_RE.findall(msg.message)):
                                if len(candidates) >= max_results:
                                    break
                                try:
                                    _add(await client.get_entity(uname))
                                except Exception:  # noqa: BLE001
                                    _drop("mention_resolve_failed")
                except Exception:  # noqa: BLE001
                    continue

        # 4) Обогащение + фильтрация кандидатов.
        rows: list[dict] = []
        for ent in list(candidates.values()):
            uname = getattr(ent, "username", None)
            input_ref = f"@{uname}" if uname else str(getattr(ent, "id", ""))
            try:
                snap = await snapshot_from_entity(client, ent, now, input_ref=input_ref)
            except Exception:  # noqa: BLE001
                _drop("enrich_failed")
                continue
            if snap is None:
                _drop("enrich_failed")
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
            "raw_count": len(candidates),
            "after_filters_count": inserted,
            "filters_breakdown": breakdown,
            "parsed_at": datetime.now(timezone.utc),
        })
        session.commit()

    log.info("parsing.discover.done", list_id=list_id,
             candidates=len(candidates), inserted=inserted, breakdown=breakdown)
    return CommunityParseResult(
        list_id=list_id, raw_count=len(candidates),
        inserted=inserted, filters_breakdown=breakdown,
    )


async def _try_add_by_peer(client, peer: PeerChannel, add, drop) -> None:
    try:
        ent = await client.get_entity(peer)
        add(ent)
    except Exception:  # noqa: BLE001
        drop("forward_resolve_failed")
