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
from modules.parsing.worker.progress import NullProgress
from modules.priming.schemas.enums import ParserSourceKind
from worker.telegram_refs import public_ref

get_logger = structlog.get_logger

PARSER_ACTION_TYPE = "priming_parser"

_MENTION_RE = re.compile(r"(?:@|t\.me/)([A-Za-z0-9_]{4,32})")
_MSG_SCAN_LIMIT = 200  # сколько постов сида сканировать для forwards/mentions
_TERM_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]{4,}")
_TERM_SPLIT_RE = re.compile(r"[,;]+")


def _split_terms(term: Optional[str]) -> list[str]:
    """«спорт, ставки, футбол» → ["спорт", "ставки", "футбол"] (без дублей).

    UI подсказывает ввод через запятую («crypto, нейросети…»), но раньше вся
    строка целиком уходила ОДНИМ запросом в Telegram-поиск, а реальная
    релевантность кандидатов словам вообще не проверялась — «похожие каналы»
    (рекомендации Telegram по сидам) не имеют отношения к введённым словам, и
    в выдачу попадало что угодно, похожее на сам канал-сид."""
    if not term:
        return []
    seen: list[str] = []
    for part in _TERM_SPLIT_RE.split(term):
        p = part.strip()
        if p and p.lower() not in (s.lower() for s in seen):
            seen.append(p)
    return seen


def _derive_term(seed_entities: list[Any]) -> Optional[str]:
    """Ключевик для глобального поиска из названий сидов, если не задан вручную.

    Берём первое «содержательное» слово (4+ букв) из названия любого сида —
    напр. «Спорт-Экспресс» → «Спорт». Без этого при пустом term глобальный
    поиск молча пропускался и discovery возвращал только сами сиды."""
    for ent in seed_entities:
        title = getattr(ent, "title", None) or ""
        m = _TERM_WORD_RE.search(title)
        if m:
            return m.group(0)
    return None


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
    # fail-open fallback: parser_run теперь всегда кладёт governor в ctx, но
    # на случай обхода dispatch (прямой вызов из других модулей/тестов) собираем
    # и здесь — Governor(None) безопасен и возвращает True.
    governor = ctx.get("governor")
    if governor is None:
        from worker.health import Governor as _Governor
        governor = _Governor(ctx.get("redis"))
    now = ctx.get("now") or datetime.now(timezone.utc)
    options = filter_options or CommunityFilterOptions()
    progress = ctx.get("parsing_progress") or NullProgress()

    if not await governor.check_and_reserve(collector_account_id, PARSER_ACTION_TYPE):
        log.info("parsing.discover.rate_limited", collector_account_id=collector_account_id)
        # Без этого лога пользователь видел «Готово (ничего не собрано/пропущено)»
        # без единого слова объяснения — выглядело как «парсинг не работает»,
        # хотя причина — простой лимит действий аккаунта (10/час, 40/день).
        progress.log(
            "Лимит действий аккаунта-парсера исчерпан (не более 10 запусков в "
            "час / 40 в сутки на один аккаунт) — попробуйте другой аккаунт-"
            "парсер или подождите."
        )
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
        if seeds:
            progress.log(f"Сиды: распознано {len(seed_entities)} из {len(seeds)}.")

        # 1) Глобальный поиск по ключевикам (через запятую — можно несколько).
        # Явно заданные слова ТАКЖЕ становятся фильтром релевантности ниже (шаг
        # 4) — иначе «похожие каналы» (ML-рекомендации Telegram по сидам, никак
        # не связанные с темой поиска) заполняют выдачу чем попало.
        explicit_terms = _split_terms(term)
        if use_search and explicit_terms:
            progress.log(
                f"Глобальный поиск Telegram по {len(explicit_terms)} "
                f"ключевик{'у' if len(explicit_terms) == 1 else 'ам'}: "
                f"{', '.join(explicit_terms)}…"
            )
            before = len(candidates)
            for kw in explicit_terms:
                if len(candidates) >= max_results:
                    break
                try:
                    res = await client(ContactsSearch(q=kw, limit=min(max_results, 100)))
                    for ch in getattr(res, "chats", None) or []:
                        if not _add(ch):
                            break
                except Exception as exc:  # noqa: BLE001
                    log.info("parsing.discover.search_failed", term=kw, error=repr(exc))
                    progress.log(f"Поиск по «{kw}» недоступен: {type(exc).__name__}.")
            progress.log(f"Поиск: +{len(candidates) - before} кандидатов.")
        elif use_search and not explicit_terms:
            # Ключевик не задан — берём слово из названия сида, иначе поиск
            # молча пропускался (возвращались только сами сиды).
            derived_term = _derive_term(seed_entities)
            if derived_term and len(candidates) < max_results:
                progress.log(f"Ключевик не задан — ищу похожие по слову «{derived_term}».")
                before = len(candidates)
                try:
                    res = await client(ContactsSearch(q=derived_term, limit=min(max_results, 100)))
                    for ch in getattr(res, "chats", None) or []:
                        if not _add(ch):
                            break
                    progress.log(f"Поиск: +{len(candidates) - before} кандидатов.")
                except Exception as exc:  # noqa: BLE001
                    log.info("parsing.discover.search_failed", error=repr(exc))
                    progress.log(f"Поиск недоступен: {type(exc).__name__}.")
            else:
                progress.log("Глобальный поиск пропущен: не задан ключевик и нет названий сидов.")

        # 2) «Похожие каналы» — BFS по рекомендациям на глубину depth.
        if use_recommendations and seed_entities:
            progress.log("Запрашиваю «похожие каналы» у Telegram…")
            before = len(candidates)
            rec_errors = 0
            first_rec_error: Optional[str] = None
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
                    except Exception as exc:  # noqa: BLE001
                        rec_errors += 1
                        if first_rec_error is None:
                            first_rec_error = f"{type(exc).__name__}: {exc}"
                        continue
                    for ch in getattr(rec, "chats", None) or []:
                        was_new = int(getattr(ch, "id", -1)) not in candidates
                        if not _add(ch):
                            break
                        if was_new and not getattr(ch, "megagroup", False):
                            next_frontier.append(ch)
                frontier = next_frontier
            found = len(candidates) - before
            if found:
                progress.log(f"Похожие каналы: +{found} кандидатов.")
            elif rec_errors:
                log.info("parsing.discover.recommendations_failed", error=first_rec_error)
                progress.log(
                    "Telegram не отдал рекомендации (возможно, аккаунт слишком "
                    f"новый или у каналов отключены похожие): {first_rec_error}."
                )
            else:
                progress.log("Похожих каналов Telegram не вернул.")
        await progress.heartbeat()

        # 3) Форварды и упоминания из постов сидов (опц., дороже).
        if (use_forwards or use_mentions) and seed_entities:
            progress.log("Сканирую посты сидов (форварды/упоминания)…")
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
        if explicit_terms and options.keywords is None:
            # Фильтр релевантности по тем же словам, что и в поиске — без
            # этого «похожие каналы» (см. выше) проходили бы без всякой связи
            # с темой. Проверяем title/about/username кандидата.
            options.keywords = explicit_terms
            progress.log(
                f"Отфильтрую кандидатов по словам: {', '.join(explicit_terms)} "
                "(название/описание/username)."
            )
        new_candidates = max(len(candidates) - len(seed_entities), 0)
        progress.log(
            f"Кандидатов всего: {len(candidates)} "
            f"(новых сверх сидов: {new_candidates}). Обогащаю и фильтрую…"
        )
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

    # Внятный итог: пользователь не должен гадать, почему «ничего не нашлось».
    seed_count = len(seed_entities)
    if inserted <= seed_count and len(candidates) <= seed_count:
        hints = []
        if not (use_search or use_recommendations):
            hints.append("включите «похожие каналы» или поиск")
        if not use_recommendations:
            hints.append("включите «похожие каналы»")
        if not (term or use_search):
            hints.append("задайте ключевик")
        tail = f" Советы: {', '.join(hints)}." if hints else (
            " Telegram не дал рекомендаций для этих каналов — попробуйте другие "
            "сиды, ключевик или включите форварды/упоминания."
        )
        progress.log(f"Готово: новых каналов не нашлось (только исходные {seed_count}).{tail}")
    else:
        progress.log(
            f"Готово: добавлено {inserted} каналов/чатов "
            f"(новых сверх сидов: {max(inserted - seed_count, 0)})."
        )

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
