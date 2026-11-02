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
from datetime import datetime, timedelta, timezone
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
from modules.commenting.worker import limits
from worker.health import around_telethon_call

get_logger = structlog.get_logger

# Жёсткий потолок на случай, если у кампании почему-то не задана глубина.
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
        # Глубина и возраст постов (§ правки): не лезем в тысячу древних.
        max_posts = campaign.existing_scope_max_posts or BACKFILL_MAX_POSTS
        max_age_days = campaign.existing_scope_max_age_days
        delay_min = campaign.posting_delay_min_sec
        delay_max = campaign.posting_delay_max_sec
        # Остаток квоты: бэкфилл НЕ должен ставить сотни заведомо лишних задач,
        # когда лимит кампании уже почти/полностью выбран (симптом «долбится на
        # все посты, хотя лимит достигнут»).
        remaining: int | None = None
        if campaign.max_comments is not None:
            remaining = max(0, campaign.max_comments - limits.posted_count(session, campaign_id))

    if remaining == 0:
        get_logger().info(
            "commenting.backfill.skip",
            account_id=account_id, channel_id=monitored_channel_id,
            reason="max_comments_reached",
        )
        return 0

    now = ctx.get("now") or datetime.now(timezone.utc)
    min_dt = now - timedelta(days=max_age_days) if max_age_days else None
    # Разносим задачи во времени: пауза между комментами = posting_delay
    # кампании. Иначе все посты улетали в очередь разом и публиковались
    # «в одну секунду» (риск бана).
    next_at = now

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

        stop = False
        while seen < max_posts and not stop:
            if seen > 0:
                await sleep(rng.uniform(*BATCH_PAUSE_SEC))
            batch_limit = min(BATCH_SIZE, max_posts - seen)
            batch = await _read_batch(client, entity, offset_id, batch_limit)
            if not batch:
                break
            seen += len(batch)

            ids = [m.id for m in batch]
            with session_factory() as session:
                already = _already_commented(session, account_id, ids)

            planned_now = 0
            for msg in batch:
                # Возрастной отсечкой режем слишком старые посты. iter_messages
                # идёт от свежих к старым — встретили старый пост, значит дальше
                # только старее: выходим целиком.
                date = getattr(msg, "date", None)
                if min_dt is not None and date is not None:
                    d = date if date.tzinfo else date.replace(tzinfo=timezone.utc)
                    if d < min_dt:
                        stop = True
                        break
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
                # Разносим во времени: каждый следующий коммент на posting_delay
                # позже предыдущего. prescheduled=True — on_channel_post не
                # добавляет свою задержку поверх (мы уже назначили время).
                next_at = next_at + timedelta(seconds=rng.uniform(delay_min, delay_max))
                await task_queue.schedule(
                    TaskName.COMMENTING_ON_CHANNEL_POST,
                    next_at,
                    account_id,
                    monitored_channel_id,
                    msg.id,
                    post_date_ts=date.timestamp() if date is not None else None,
                    prescheduled=True,
                    **({"post_text": text} if text else {}),
                )
                scheduled += 1
                planned_now += 1
                # Квота кампании: больше, чем осталось, ставить незачем.
                if remaining is not None and scheduled >= remaining:
                    stop = True
                    break

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
