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
from modules.parsing.worker.progress import NullProgress
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
    max_targets: Optional[int] = None,
    filter_options: Optional[FilterOptions] = None,
) -> Optional[ParseResult]:
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
    progress = ctx.get("parsing_progress") or NullProgress()

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

    progress.log(f"Открываю {chat_ref} и читаю участников…")
    client = await pool.get(collector_account_id)
    raw_rows: list[dict[str, Any]] = []
    # pre_breakdown: отсеивания ДО фильтров (напр. only_recently_seen) —
    # раньше они молча терялись: пользователь видел raw_count=0 и думал, что
    # парсинг «ничего не делает», хотя чат на 50k. Теперь показываем в логе.
    pre_breakdown: dict[str, int] = {}
    total_seen = 0
    try:
        entity = await client.get_entity(chat_ref)
        # Чтобы перечислять участников, аккаунт обычно должен СОСТОЯТЬ в чате:
        # у не-участника Telegram отдаёт лишь админов (или пусто) — отсюда
        # «на чат 15k вернуло 2 юзернейма». Вступаем best-effort перед сбором.
        await _ensure_member(client, entity, progress, log,
                             account_id=collector_account_id,
                             session_factory=session_factory,
                             publisher=ctx.get("publisher"))
        # aggressive=True заставляет Telethon обходить участников по буквам
        # (а не упираться в ~первые отданные сервером), иначе на крупных группах
        # собирается лишь малая часть.
        async for participant in client.iter_participants(entity, aggressive=True):
            total_seen += 1
            snap = _snapshot(participant, now)
            if only_recently_seen and snap["last_seen_bucket"] not in {
                TargetLastSeen.RECENTLY.value,
                TargetLastSeen.WITHIN_WEEK.value,
            }:
                pre_breakdown["not_recently_seen"] = (
                    pre_breakdown.get("not_recently_seen", 0) + 1
                )
                continue
            raw_rows.append(snap)
            if len(raw_rows) % 50 == 0:
                progress.log(f"Просмотрено {total_seen}, собрано {len(raw_rows)}…")
                await progress.heartbeat(raw=len(raw_rows))
            # Остановка по запрошенному лимиту «сколько юзеров нужно».
            if max_targets is not None and len(raw_rows) >= max_targets:
                progress.log(f"Достигнут лимит {max_targets} — останавливаю сбор.")
                break
    finally:
        await pool.release(collector_account_id)
    # Диагностика «вернуло подозрительно мало»: у не-участника/закрытого чата
    # так и будет — подсказываем пользователю, почему.
    if total_seen <= 5:
        progress.log(
            f"⚠ Из «{chat_ref}» видно лишь {total_seen} участников. Обычно это "
            "значит, что аккаунт-парсер не состоит в чате, либо чат скрывает "
            "список участников (большие/закрытые группы). Добавьте аккаунт в чат "
            "вручную и повторите, либо используйте парсинг по комментаторам/"
            "сообщениям."
        )
    progress.log(
        f"Сбор завершён: просмотрено {total_seen}, собрано {len(raw_rows)}. "
        f"Применяю фильтры…"
    )

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
                        "first_name": r.get("first_name"),
                        "last_name": r.get("last_name"),
                        "last_seen_bucket": r.get("last_seen_bucket") or TargetLastSeen.UNKNOWN.value,
                    }
                    for r in outcome.kept
                ],
            )
        breakdown = dict(outcome.breakdown)
        # Отсеивания ДО фильтров (only_recently_seen) тоже видимы юзеру,
        # чтобы не казалось, что парсер «ничего не собрал».
        for reason, cnt in pre_breakdown.items():
            breakdown[reason] = breakdown.get(reason, 0) + cnt
        already = len(outcome.kept) - inserted
        if already > 0:
            breakdown["already_in_list"] = already
        ParsedListRepository(session).update(list_id, {
            "raw_count": total_seen,
            "after_filters_count": inserted,
            "filters_breakdown": breakdown,
            "parsed_at": datetime.now(timezone.utc),
        })
        session.commit()

    progress.set_counts(raw=total_seen, inserted=inserted)
    progress.log(
        f"Фильтры применены: добавлено {inserted} из {total_seen} просмотренных."
    )
    log.info(
        "parsing.chat_members.done", list_id=list_id,
        raw=total_seen, inserted=inserted, breakdown=breakdown,
    )
    return ParseResult(
        list_id=list_id, raw_count=total_seen,
        inserted=inserted, filters_breakdown=breakdown,
    )


async def _ensure_member(
    client: Any,
    entity: Any,
    progress: Any,
    log: Any,
    *,
    account_id: int,
    session_factory: Any,
    publisher: Any,
) -> None:
    """Best-effort: вступить аккаунтом-парсером в чат перед перечислением.

    Для не-участника Telegram почти всегда отдаёт лишь админов — список
    получается в единицы вместо тысяч. Если аккаунт уже в чате — JoinChannel
    идемпотентен. Ошибку не роняем: просто попробуем читать как есть."""
    if getattr(entity, "left", None) is False:
        return  # уже участник — вступать не нужно
    from telethon.tl.functions.channels import JoinChannelRequest

    from worker.health import around_telethon_call

    try:
        await around_telethon_call(
            lambda: client(JoinChannelRequest(entity)),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
    except Exception as exc:  # noqa: BLE001 — join best-effort
        log.info("parsing.chat_members.join_skipped", error=repr(exc))
        progress.log(
            "Не удалось вступить в чат аккаунтом-парсером — читаю как есть "
            f"({type(exc).__name__})."
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
