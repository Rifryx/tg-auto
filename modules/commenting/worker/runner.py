"""Раннер модуля commenting: on_new_post и post_comment (PROJECT-STAGES §5, §8.3).

Порядок: новый пост → on_new_post выбирает N аккаунтов, генерирует комментарии
(LLM + StyleRandomizer) и планирует их постинг с задержками → post_comment
резервирует слот governor, шлёт реплай через ClientPool (обёрнуто в
around_telethon_call) и пишет CommentLog. После успешного коммента с шансом
CONTINUE — второй раунд треда (ответ на свой же коммент), глубина ≤ MAX_DEPTH.

Инъекции через ctx (для тестов): now, rng, client_pool, task_queue, governor,
llm_provider, publisher.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from core.enums import CommentStatus
from core.queue import TaskQueue
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from core.repositories.persona import PersonaRepository
from modules.commenting.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    CommentLogRepository,
)
from modules.commenting.schemas import CommentLogCreate
from worker.client_pool import ClientPool
from worker.health import Governor, around_telethon_call
from worker.llm import Message, StyleRandomizer, get_provider
from worker.tasks.logging import get_logger

# --- параметры (§5) ----------------------------------------------------------
MIN_ACCOUNTS_PER_POST = 2
MAX_ACCOUNTS_PER_POST = 4
THREAD_CONTINUE_PROB = 0.35
MAX_THREAD_DEPTH = 3
GOVERNOR_RETRY_MINUTES = 5


# --- ctx-инъекции ------------------------------------------------------------


def _now(ctx: dict) -> datetime:
    return ctx.get("now") or datetime.now(timezone.utc)


def _rng(ctx: dict) -> random.Random:
    return ctx.get("rng") or random.Random()


def _task_queue(ctx: dict) -> TaskQueue:
    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


def _governor(ctx: dict) -> Governor:
    return ctx.get("governor") or Governor(ctx.get("redis"))


def _style(ctx: dict) -> StyleRandomizer:
    return ctx.get("style_randomizer") or StyleRandomizer(_rng(ctx))


# --- helpers -----------------------------------------------------------------


def is_within_active_hours(now: datetime, campaign) -> bool:
    try:
        tz = ZoneInfo(campaign.active_hours_tz)
    except Exception:  # pragma: no cover
        tz = ZoneInfo("UTC")
    local = now.astimezone(tz).timetz().replace(tzinfo=None)
    start, end = campaign.active_hours_start, campaign.active_hours_end
    if start <= end:
        return start <= local <= end
    return local >= start or local <= end


def _assigned_accounts(session, campaign_id: int) -> list:
    links = CampaignAccountRepository(session).list_by_campaign(campaign_id)
    accounts_repo = AccountRepository(session)
    result = []
    for link in links:
        account = accounts_repo.get(link.account_id)
        if account is not None and account.status == "assigned":
            result.append(account)
    return result


def _build_system_prompt(session, campaign, account) -> str:
    override = CampaignAccountRepository(session).get(campaign.id, account.id)
    prompt = (override.override_prompt if override and override.override_prompt else None)
    prompt = prompt or campaign.base_system_prompt
    if account.persona_id is not None:
        persona = PersonaRepository(session).get(account.persona_id)
        if persona is not None:
            tags = ", ".join(persona.personality_tags or [])
            prompt = f"{prompt}\n\nТы — {persona.name}. Черты: {tags}."
    return prompt


def _thread_context(session, campaign_id: int, channel_msg_id: int) -> list[Message]:
    logs = CommentLogRepository(session).list_by_campaign(campaign_id, limit=100)
    thread = [
        log for log in logs
        if log.post_channel_msg_id == channel_msg_id and log.status == CommentStatus.POSTED.value
    ]
    thread.sort(key=lambda log: log.id)
    messages = [Message(role="user", content=f"Пост #{channel_msg_id}")]
    messages += [Message(role="assistant", content=log.comment_text) for log in thread]
    return messages


def _persona_for(session, account):
    if account.persona_id is None:
        return None
    return PersonaRepository(session).get(account.persona_id)


# --- задача on_new_post ------------------------------------------------------


async def on_new_post(
    ctx: dict,
    campaign_id: int,
    channel_msg_id: int,
    in_reply_to: Optional[int] = None,
    thread_depth: int = 0,
) -> int:
    now = _now(ctx)
    rng = _rng(ctx)
    session_factory = ctx["session_factory"]
    task_queue = _task_queue(ctx)
    log = get_logger()

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None or not campaign.enabled:
            log.info("commenting.on_new_post.skip", campaign_id=campaign_id, reason="disabled")
            return 0
        if not is_within_active_hours(now, campaign):
            log.info("commenting.on_new_post.skip", campaign_id=campaign_id, reason="inactive_hours")
            return 0

        accounts = _assigned_accounts(session, campaign_id)
        if not accounts:
            log.info("commenting.on_new_post.skip", campaign_id=campaign_id, reason="no_accounts")
            return 0

        n_hi = min(MAX_ACCOUNTS_PER_POST, len(accounts))
        n_lo = min(MIN_ACCOUNTS_PER_POST, len(accounts))
        chosen = rng.sample(accounts, rng.randint(n_lo, n_hi))

        reply_target = in_reply_to if in_reply_to is not None else channel_msg_id
        provider = ctx.get("llm_provider") or get_provider(campaign.llm_provider)
        style = _style(ctx)
        delay_lo = campaign.posting_delay_min_sec
        delay_hi = campaign.posting_delay_max_sec

        plans = []
        for account in chosen:
            system = _build_system_prompt(session, campaign, account)
            context = _thread_context(session, campaign_id, channel_msg_id)
            raw = await provider.generate(system, context)
            text = style.randomize(raw, _persona_for(session, account))
            delay = rng.uniform(delay_lo, delay_hi)
            plans.append((account.id, text, delay))

    for account_id, text, delay in plans:
        run_at = now + timedelta(seconds=delay)
        await task_queue.schedule(
            TaskName.COMMENTING_POST_COMMENT,
            run_at,
            campaign_id,
            account_id,
            text,
            channel_msg_id,
            reply_target,
            thread_depth=thread_depth,
        )
    log.info(
        "commenting.on_new_post.scheduled",
        campaign_id=campaign_id,
        channel_msg_id=channel_msg_id,
        count=len(plans),
        thread_depth=thread_depth,
    )
    return len(plans)


# --- задача post_comment -----------------------------------------------------


async def post_comment(
    ctx: dict,
    campaign_id: int,
    account_id: int,
    text: str,
    channel_msg_id: int,
    in_reply_to_message_id: int,
    thread_depth: int = 0,
) -> Optional[int]:
    now = _now(ctx)
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    task_queue = _task_queue(ctx)
    log = get_logger()

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None:
            log.info("commenting.post_comment.skip", account_id=account_id, reason="no_campaign")
            return None
        if not is_within_active_hours(now, campaign):
            log.info("commenting.post_comment.skip", account_id=account_id, reason="inactive_hours")
            return None
        discussion_group_id = campaign.discussion_group_id

    # rate-limit governor
    if not await _governor(ctx).check_and_reserve(account_id, "comment"):
        run_at = now + timedelta(minutes=GOVERNOR_RETRY_MINUTES)
        await task_queue.schedule(
            TaskName.COMMENTING_POST_COMMENT,
            run_at,
            campaign_id,
            account_id,
            text,
            channel_msg_id,
            in_reply_to_message_id,
            thread_depth=thread_depth,
        )
        log.info("commenting.post_comment.rate_limited", account_id=account_id)
        return None

    pool = _pool(ctx)
    client = await pool.get(account_id)
    try:
        sent = await around_telethon_call(
            lambda: client.send_message(
                discussion_group_id, text, reply_to=in_reply_to_message_id
            ),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            now=now,
        )
    finally:
        await pool.release(account_id)

    posted_message_id = getattr(sent, "id", None)
    with session_factory() as session:
        CommentLogRepository(session).create(
            CommentLogCreate(
                campaign_id=campaign_id,
                account_id=account_id,
                post_channel_msg_id=channel_msg_id,
                comment_text=text,
                status=CommentStatus.POSTED,
                posted_message_id=posted_message_id,
                in_reply_to_message_id=in_reply_to_message_id,
            )
        )
        session.commit()

    log.info(
        "commenting.post_comment.posted",
        account_id=account_id,
        posted_message_id=posted_message_id,
        thread_depth=thread_depth,
    )
    await maybe_continue_thread(ctx, campaign_id, channel_msg_id, posted_message_id, thread_depth)
    return posted_message_id


async def maybe_continue_thread(
    ctx: dict,
    campaign_id: int,
    channel_msg_id: int,
    comment_msg_id: Optional[int],
    thread_depth: int,
) -> bool:
    """Тред-симуляция: с шансом CONTINUE запускает ответ на свой коммент (≤ глубины)."""
    if comment_msg_id is None or thread_depth >= MAX_THREAD_DEPTH:
        return False
    if _rng(ctx).random() >= THREAD_CONTINUE_PROB:
        return False
    await _task_queue(ctx).enqueue(
        TaskName.COMMENTING_ON_NEW_POST,
        campaign_id,
        channel_msg_id,
        in_reply_to=comment_msg_id,
        thread_depth=thread_depth + 1,
    )
    get_logger().info(
        "commenting.thread.continue",
        campaign_id=campaign_id,
        in_reply_to=comment_msg_id,
        next_depth=thread_depth + 1,
    )
    return True
