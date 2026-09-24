"""Backfill истории канала для post_scope='existing'|'mixed' (E2.1).

Одноразовый проход по истории канала аккаунта после того, как канал
разрешён. Для каждого поста применяет тот же фильтр (keywords/probability),
что и listener, планирует ``on_channel_post`` с реальной датой поста
(для окна after_post_sec).

Читает батчами (BATCH_SIZE), между батчами спит BATCH_PAUSE_SEC —
непрогретый аккаунт на 1000+ сообщений подряд гарантированно словит
FloodWait. Hard cap ``BACKFILL_MAX_POSTS`` не даёт залить кампанию
тысячей задач с большого канала.

Дедуп: если аккаунт уже комментировал этот пост (post_channel_msg_id),
второй раз не планируем.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Callable

import structlog
from sqlalchemy import select

from core.enums import CommentStatus
from core.queue.task_names import TaskName
from modules.commenting.models import CommentLog
from modules.commenting.repositories import (
    CampaignRepository,
    MonitoredChannelRepository,
)
from worker.health import around_telethon_call

get_logger = structlog.get_logger

BACKFILL_MAX_POSTS = 200
BATCH_SIZE = 100
BATCH_PAUSE_SEC = (60.0, 120.0)


def _rng(ctx: dict) -> random.Random:
    return ctx.get("rng") or random.Random()


def _sleep(ctx: dict) -> Callable[..., Any]:
    return ctx.get("sleep") or asyncio.sleep


def _pool(ctx: dict):
    pool = ctx.get("client_pool")
    if pool is None:
        from worker.client_pool import ClientPool

        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


def _task_queue(ctx: dict):
    from core.queue import TaskQueue

    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


def _already_commented(session, account_id: int, msg_ids: list[int]) -> set[int]:
    if not msg_ids:
        return set()
    rows = session.execute(
        select(CommentLog.post_channel_msg_id).where(
            CommentLog.account_id == account_id,
            CommentLog.post_channel_msg_id.in_(msg_ids),
            CommentLog.status == CommentStatus.POSTED.value,
        )
    ).scalars()
    return set(rows)


async def _read_batch(client, entity, offset_id: int, limit: int) -> list:
    batch = []
    async for msg in client.iter_messages(entity, limit=limit, offset_id=offset_id):
        batch.append(msg)
    return batch


async def backfill_channel(ctx: dict, account_id: int, monitored_channel_id: int) -> int:
    """Идёт по истории канала и ставит on_channel_post для подходящих постов.

    Возвращает число запланированных задач.
    """
    session_factory = ctx["session_factory"]
    task_queue = _task_queue(ctx)
    log = get_logger()
    rng = _rng(ctx)
    sleep = _sleep(ctx)

    with session_factory() as session:
        ch = MonitoredChannelRepository(session).get(monitored_channel_id)
        if ch is None or ch.status != "working" or ch.channel_tg_id is None:
            log.info(
                "commenting.backfill.skip",
                account_id=account_id, channel_id=monitored_channel_id,
                reason="channel_not_working",
            )
            return 0
        campaign_id = ch.source_campaign_id
        if campaign_id is None:
            log.info(
                "commenting.backfill.skip",
                channel_id=monitored_channel_id, reason="not_campaign_owned",
            )
            return 0
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None or not campaign.enabled:
            return 0
        if campaign.post_scope not in ("existing", "mixed"):
            log.info(
                "commenting.backfill.skip",
                channel_id=monitored_channel_id, reason="post_scope_new_only",
            )
            return 0
        channel_tg_id = ch.channel_tg_id
        selection_mode = campaign.post_selection_mode
        keywords = list(campaign.keywords or [])
        probability = campaign.probability_percent

    pool = _pool(ctx)
    client = await pool.get(account_id)
    scheduled = 0
    seen = 0
    # offset_id=0 — «с самого свежего»; для каждой следующей пачки берём
    # min(id) предыдущей, чтобы двигаться в прошлое без пересечений.
    offset_id = 0
    # listener → worker.tasks (для get_logger) → замыкает импорт; лениво.
    from modules.commenting.worker.listener import _passes_post_filter

    try:
        entity = await around_telethon_call(
            lambda: client.get_entity(channel_tg_id),
            account_id=account_id,
            session_factory=session_factory,
            publisher=ctx.get("publisher"),
            now=ctx.get("now"),
        )

        while seen < BACKFILL_MAX_POSTS:
            if seen > 0:
                await sleep(rng.uniform(*BATCH_PAUSE_SEC))
            batch_limit = min(BATCH_SIZE, BACKFILL_MAX_POSTS - seen)
            batch = await _read_batch(client, entity, offset_id, batch_limit)
            if not batch:
                break
            seen += len(batch)

            ids = [m.id for m in batch]
            with session_factory() as session:
                already = _already_commented(session, account_id, ids)

            planned_now = 0
            for msg in batch:
                if msg.id in already:
                    continue
                text = getattr(msg, "message", None) or getattr(msg, "text", None)
                if not _passes_post_filter(
                    text,
                    mode=selection_mode,
                    keywords=keywords,
                    probability_percent=probability,
                    rng=rng,
                ):
                    continue
                date = getattr(msg, "date", None)
                await task_queue.enqueue(
                    TaskName.COMMENTING_ON_CHANNEL_POST,
                    account_id,
                    monitored_channel_id,
                    msg.id,
                    post_date_ts=date.timestamp() if date is not None else None,
                )
                scheduled += 1
                planned_now += 1

            log.info(
                "commenting.backfill.batch",
                account_id=account_id, channel_id=monitored_channel_id,
                seen=seen, planned=planned_now,
            )

            if len(batch) < batch_limit:
                break
            offset_id = min(ids)
    finally:
        await pool.release(account_id)

    log.info(
        "commenting.backfill.done",
        account_id=account_id, channel_id=monitored_channel_id,
        scheduled=scheduled,
    )
    return scheduled
