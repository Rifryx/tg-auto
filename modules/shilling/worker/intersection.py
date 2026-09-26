"""Поиск целей «по пересечению каналов» (TargetsTab → «По пересечению каналов»).

Читает подписки аккаунтов кампании через Telethon и находит каналы с открытыми
комментариями, на которые подписаны сразу несколько аккаунтов. Результат
публикуется в Redis-канал ``shilling.intersection.{job_id}`` — SSE-эндпоинт
транслирует прогресс и итоговый список в браузер, где пользователь выбирает,
какие каналы добавить в цели.

Двухфазный алгоритм (щадит FloodWait):
  1. По каждому аккаунту — один ``get_dialogs`` — собираем каналы-трансляции
     и считаем, у скольких аккаунтов канал есть.
  2. Только для каналов, прошедших порог пересечения, один раз проверяем
     наличие группы обсуждения (``GetFullChannelRequest``) с probe-аккаунта.

Инъекции через ctx: session_factory, now, rng, sleep, client_pool, publisher.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Any

import structlog

from core.repositories.account import AccountRepository
from modules.shilling.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
)
from modules.shilling.schemas import DiscoveredChannel, IntersectionReport
from worker.client_pool import ClientPool
from worker.health import around_telethon_call

get_logger = structlog.get_logger

# Аккаунты, чьи подписки имеет смысл читать (не забанены/не выведены).
_USABLE_ACCOUNT_STATUSES = {"pool", "assigned"}

# Ограничения против FloodWait (как в commenting.sync_account_subscriptions).
SCAN_MAX_CHANNELS = 500  # максимум каналов из диалогов одного аккаунта
FULL_CHECK_PAUSE_SEC = (1.0, 3.0)  # пауза между GetFullChannelRequest


def intersection_channel(job_id: str) -> str:
    return f"shilling.intersection.{job_id}"


def _now(ctx: dict) -> datetime:
    return ctx.get("now") or datetime.now(timezone.utc)


def _rng(ctx: dict) -> random.Random:
    return ctx.get("rng") or random.Random()


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


def _publish(ctx: dict, channel: str, payload: dict[str, Any]) -> None:
    publisher = ctx.get("publisher")
    if publisher is not None:
        publisher.publish(channel, payload)


async def discover_intersection(
    ctx: dict,
    campaign_id: int,
    job_id: str,
    min_accounts: int = 2,
) -> IntersectionReport:
    """Находит каналы-пересечения по подпискам аккаунтов кампании."""
    channel = intersection_channel(job_id)
    session_factory = ctx["session_factory"]
    now = _now(ctx)
    rng = _rng(ctx)
    sleep = ctx.get("sleep") or asyncio.sleep
    log = get_logger()
    min_accounts = max(1, int(min_accounts))

    def _fail(reason: str) -> IntersectionReport:
        report = IntersectionReport(
            job_id=job_id, ok=False, reason=reason, min_accounts=min_accounts
        )
        _publish(ctx, channel, {"event": "done", **report.model_dump()})
        return report

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None:
            return _fail("campaign not found")
        links = CampaignAccountRepository(session).list_by_campaign(campaign_id)
        acc_repo = AccountRepository(session)
        account_ids: list[int] = []
        for link in links:
            acc = acc_repo.get(link.account_id)
            if acc is not None and acc.status in _USABLE_ACCOUNT_STATUSES:
                account_ids.append(link.account_id)
        existing_targets = {
            t.raw_input for t in CampaignTargetRepository(session).list_by_campaign(campaign_id)
        }

    account_ids = list(dict.fromkeys(account_ids))  # дедуп, порядок сохранён
    total = len(account_ids)
    if total == 0:
        return _fail("no usable accounts in campaign")

    _publish(ctx, channel, {"event": "start", "job_id": job_id, "accounts_total": total})

    async def _call(account_id: int, factory):
        return await around_telethon_call(
            factory, account_id=account_id, session_factory=session_factory,
            publisher=ctx.get("publisher"), now=now,
        )

    pool = _pool(ctx)
    # channel_tg_id -> {"count", "username", "title"}
    found: dict[int, dict[str, Any]] = {}
    scanned = 0

    # --- Фаза 1: собираем подписки каждого аккаунта -------------------------
    for account_id in account_ids:
        try:
            client = await pool.get(account_id)
        except Exception as exc:  # noqa: BLE001 — забанен/недоступен: пропускаем
            log.info("shilling.intersection.account_skip", account_id=account_id,
                     reason=type(exc).__name__)
            _publish(ctx, channel, {
                "event": "account_error", "account_id": account_id,
                "reason": type(exc).__name__,
            })
            continue
        try:
            dialogs = await _call(account_id, lambda: client.get_dialogs(limit=None))
            seen: set[int] = set()
            for dialog in dialogs:
                if len(seen) >= SCAN_MAX_CHANNELS:
                    break
                ent = getattr(dialog, "entity", None)
                if not getattr(ent, "broadcast", False) or getattr(ent, "left", False):
                    continue
                if ent.id in seen:
                    continue
                seen.add(ent.id)
                rec = found.get(ent.id)
                if rec is None:
                    rec = {
                        "count": 0,
                        "username": getattr(ent, "username", None),
                        "title": getattr(ent, "title", None),
                    }
                    found[ent.id] = rec
                rec["count"] += 1
            scanned += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("shilling.intersection.scan_failed", account_id=account_id,
                        reason=type(exc).__name__)
            _publish(ctx, channel, {
                "event": "account_error", "account_id": account_id,
                "reason": type(exc).__name__,
            })
        finally:
            await pool.release(account_id)
        _publish(ctx, channel, {
            "event": "account_done", "scanned": scanned, "total": total,
        })

    # --- Фаза 2: только каналы выше порога и с @username проверяем на комменты
    candidates = [
        (cid, rec) for cid, rec in found.items()
        if rec["count"] >= min_accounts and rec["username"]
    ]
    # Сначала самые «общие» — их проверяем раньше на случай FloodWait.
    candidates.sort(key=lambda item: item[1]["count"], reverse=True)

    channels: list[DiscoveredChannel] = []
    if candidates:
        from telethon.tl.functions.channels import GetFullChannelRequest

        probe_id = account_ids[0]
        try:
            probe = await pool.get(probe_id)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"probe account unavailable: {type(exc).__name__}")
        try:
            for cid, rec in candidates:
                username = rec["username"]
                try:
                    ent = await _call(probe_id, lambda u=username: probe.get_entity(u))
                    full = await _call(probe_id, lambda e=ent: probe(GetFullChannelRequest(e)))
                except Exception as exc:  # noqa: BLE001 — приватный/удалён/недоступен
                    log.info("shilling.intersection.full_failed", username=username,
                             reason=type(exc).__name__)
                    continue
                linked = getattr(getattr(full, "full_chat", None), "linked_chat_id", None)
                await sleep(rng.uniform(*FULL_CHECK_PAUSE_SEC))
                if not linked:
                    continue  # комментарии выключены — как цель бесполезен
                raw_input = username.lower()
                channels.append(DiscoveredChannel(
                    chat_id=cid,
                    username=username,
                    title=rec["title"],
                    raw_input=raw_input,
                    subscriber_count=rec["count"],
                    already_target=raw_input in existing_targets,
                ))
                _publish(ctx, channel, {"event": "channel", **channels[-1].model_dump()})
        finally:
            await pool.release(probe_id)

    channels.sort(key=lambda c: (c.subscriber_count, c.title or ""), reverse=True)
    report = IntersectionReport(
        job_id=job_id,
        ok=True,
        channels=channels,
        accounts_total=total,
        accounts_scanned=scanned,
        min_accounts=min_accounts,
    )
    _publish(ctx, channel, {"event": "done", **report.model_dump()})
    log.info(
        "shilling.intersection.done", job_id=job_id, campaign_id=campaign_id,
        accounts_scanned=scanned, found=len(channels), min_accounts=min_accounts,
    )
    return report
