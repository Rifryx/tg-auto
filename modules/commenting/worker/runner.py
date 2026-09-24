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
    MonitoredChannelRepository,
)
from modules.commenting.schemas import CommentLogCreate
import structlog

from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatGuestSendForbiddenError,
    ChatWriteForbiddenError,
    UserBannedInChannelError,
    UserNotParticipantError,
)

from modules.commenting.worker import limits
from modules.commenting.worker.alerts import auto_blacklist, raise_alert
from worker.client_pool import ClientPool
from worker.health import Governor, around_telethon_call
from worker.llm import Message, StyleRandomizer, get_provider

get_logger = structlog.get_logger

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
    # Персона аккаунта перекрывает персону кампании; кампания — дефолт для тех,
    # у кого своей нет.
    persona_id = account.persona_id or getattr(campaign, "persona_id", None)
    if persona_id is not None:
        persona = PersonaRepository(session).get(persona_id)
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


def _blacklisted(session, campaign_id: int, *, chat_id: Optional[int], ref: Optional[str]) -> bool:
    """Канал в чёрном списке кампании (по id канала или username без «@»)."""
    from modules.commenting.repositories import ChannelBlacklistRepository

    username = (ref or "").lstrip("@") or None
    return (
        ChannelBlacklistRepository(session).find(campaign_id, chat_id=chat_id, username=username)
        is not None
    )


# Ошибки доступа при отправке (E3.2). Не роняем задачу (иначе воркер
# повторит отправку впустую), а разбираем: лог + алерт + действие.
_NO_ACCESS = (ChannelPrivateError, ChannelInvalidError)
_NOT_MEMBER = (UserNotParticipantError, ChatGuestSendForbiddenError)
_NO_RIGHTS = (ChatWriteForbiddenError, UserBannedInChannelError, ChatAdminRequiredError)
ACCESS_ERRORS = _NO_ACCESS + _NOT_MEMBER + _NO_RIGHTS


async def _handle_access_error(
    ctx: dict,
    exc: Exception,
    *,
    campaign_id: int,
    account_id: int,
    channel_msg_id: int,
    text: str,
    reply_to: int,
    channel_ref: Optional[str],
    channel_tg_id: Optional[int],
    monitored_channel_id: Optional[int],
    blacklist_username: Optional[str] = None,
) -> None:
    """channel_ref — ключ алертов (исходная ссылка, как у резолвера, чтобы он
    сам закрыл алерт после переподписки); blacklist_username — username канала
    для ЧС."""
    from modules.commenting.worker.channels import ACTION_DETACH, publish_channel_lifecycle

    publisher = ctx.get("publisher")
    err = type(exc).__name__
    ref = channel_ref or (f"tg:{channel_tg_id}" if channel_tg_id else "?")
    rejoin = False
    detach = False

    with ctx["session_factory"]() as session:
        CommentLogRepository(session).create(
            CommentLogCreate(
                campaign_id=campaign_id, account_id=account_id,
                post_channel_msg_id=channel_msg_id, comment_text=text,
                status=CommentStatus.FAILED, in_reply_to_message_id=reply_to,
                error=f"access:{err}",
            )
        )
        session.commit()
        mon_repo = MonitoredChannelRepository(session)

        if isinstance(exc, _NO_ACCESS):
            # Канал закрыт/недоступен — в ЧС кампании, чтобы не пытаться снова.
            username = (blacklist_username or channel_ref or "").lstrip("@") or None
            if username and username.startswith("tg:"):
                username = None
            added = (channel_tg_id is not None or username is not None) and auto_blacklist(
                session, campaign_id=campaign_id, chat_id=channel_tg_id,
                username=username, reason=err,
            )
            if added:
                raise_alert(
                    session, publisher, campaign_id=campaign_id, account_id=account_id,
                    channel_ref=ref, kind="blacklisted",
                    detail=f"Канал недоступен ({err}) — добавлен в чёрный список кампании.",
                )
            detach = True
        elif isinstance(exc, _NOT_MEMBER):
            campaign = CampaignRepository(session).get(campaign_id)
            subscribe = campaign is not None and campaign.on_not_subscribed_action == "subscribe_and_notify"
            raise_alert(
                session, publisher, campaign_id=campaign_id, account_id=account_id,
                channel_ref=ref, kind="not_subscribed",
                detail=(
                    "Аккаунт не состоит в канале/обсуждении — подписываем заново."
                    if subscribe and monitored_channel_id
                    else "Аккаунт не состоит в канале/обсуждении — коммент не отправлен."
                ),
            )
            rejoin = bool(subscribe and monitored_channel_id)
            detach = not rejoin
        else:
            raise_alert(
                session, publisher, campaign_id=campaign_id, account_id=account_id,
                channel_ref=ref, kind="access_lost",
                detail=f"Нет прав писать в обсуждение ({err}).",
            )
            detach = True

        if monitored_channel_id is not None:
            if rejoin:
                row = mon_repo.get(monitored_channel_id)
                if row is not None:
                    row.status = "pending"
                    row.error = None
            else:
                mon_repo.mark_failed(monitored_channel_id, f"access:{err}")
            session.commit()

    if monitored_channel_id is not None:
        if rejoin:
            await _task_queue(ctx).enqueue(TaskName.COMMENTING_RESOLVE_CHANNEL, monitored_channel_id)
        if detach or rejoin:
            publish_channel_lifecycle(publisher, account_id, monitored_channel_id, ACTION_DETACH)
    get_logger().warning(
        "commenting.post.access_error", account_id=account_id, campaign_id=campaign_id,
        error=err, rejoin=rejoin,
    )


def _limit_skip_reason(session, campaign, post_date_ts: Optional[float], now: datetime) -> Optional[str]:
    """Причина не комментировать по лимитам кампании (E2.2) или None."""
    if limits.max_comments_reached(session, campaign):
        return "max_comments_reached"
    if limits.window_closed(campaign, limits.post_date_from_ts(post_date_ts), now):
        return "window_closed"
    return None


async def _generate(ctx, session, campaign, account, provider, context) -> tuple[str, bool]:
    """Текст коммента с учётом min_words (до 3 попыток)."""
    system = _build_system_prompt(session, campaign, account)
    persona = _persona_for(session, account)
    style = _style(ctx)

    async def once() -> str:
        raw = await provider.generate(system, context)
        return style.randomize(raw, persona)

    return await limits.generate_with_min_words(once, campaign.min_words or 0)


def _log_below_min_words(session, campaign, account_id, channel_msg_id, text, reply_to) -> None:
    """Не набрали min_words — коммент не шлём, но фиксируем в логе/статистике."""
    CommentLogRepository(session).create(
        CommentLogCreate(
            campaign_id=campaign.id,
            account_id=account_id,
            post_channel_msg_id=channel_msg_id,
            comment_text=text,
            status=CommentStatus.FAILED,
            in_reply_to_message_id=reply_to,
            error=f"below_min_words:{campaign.min_words}",
        )
    )
    session.commit()


# --- задача on_new_post ------------------------------------------------------


async def on_new_post(
    ctx: dict,
    campaign_id: int,
    channel_msg_id: int,
    in_reply_to: Optional[int] = None,
    thread_depth: int = 0,
    post_date_ts: Optional[float] = None,
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
        reason = _limit_skip_reason(session, campaign, post_date_ts, now)
        if reason:
            log.info("commenting.on_new_post.skip", campaign_id=campaign_id, reason=reason)
            return 0
        if _blacklisted(session, campaign_id, chat_id=None, ref=campaign.target_channel):
            log.info("commenting.on_new_post.skip", campaign_id=campaign_id, reason="blacklisted")
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
        delay_lo = campaign.posting_delay_min_sec
        delay_hi = campaign.posting_delay_max_sec

        plans = []
        for account in chosen:
            context = _thread_context(session, campaign_id, channel_msg_id)
            text, ok = await _generate(ctx, session, campaign, account, provider, context)
            if not ok:
                _log_below_min_words(session, campaign, account.id, channel_msg_id, text, reply_target)
                log.info("commenting.on_new_post.skip_account", account_id=account.id, reason="below_min_words")
                continue
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
            post_date_ts=post_date_ts,
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
    post_date_ts: Optional[float] = None,
) -> Optional[int]:
    now = _now(ctx)
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    task_queue = _task_queue(ctx)
    log = get_logger()

    async def reschedule(run_at: datetime) -> None:
        await task_queue.schedule(
            TaskName.COMMENTING_POST_COMMENT,
            run_at,
            campaign_id,
            account_id,
            text,
            channel_msg_id,
            in_reply_to_message_id,
            thread_depth=thread_depth,
            post_date_ts=post_date_ts,
        )

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None:
            log.info("commenting.post_comment.skip", account_id=account_id, reason="no_campaign")
            return None
        if not is_within_active_hours(now, campaign):
            log.info("commenting.post_comment.skip", account_id=account_id, reason="inactive_hours")
            return None
        # Лимиты перепроверяем при отправке: между планированием и отправкой
        # мог набраться max_comments или закрыться окно.
        reason = _limit_skip_reason(session, campaign, post_date_ts, now)
        if reason:
            log.info("commenting.post_comment.skip", account_id=account_id, reason=reason)
            return None
        wait = limits.pause_wait_until(
            CampaignAccountRepository(session).get(campaign_id, account_id), campaign, now
        )
        discussion_group_id = campaign.discussion_group_id
        target_channel = campaign.target_channel

    if wait is not None:
        await reschedule(wait)
        log.info("commenting.post_comment.paused", account_id=account_id, until=wait.isoformat())
        return None

    # rate-limit governor
    if not await _governor(ctx).check_and_reserve(account_id, "comment"):
        await reschedule(now + timedelta(minutes=GOVERNOR_RETRY_MINUTES))
        log.info("commenting.post_comment.rate_limited", account_id=account_id)
        return None

    # Занимаем слот паузы атомарно (FOR UPDATE): гонка двух задач аккаунта.
    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        wait = limits.claim_post_slot(session, campaign, account_id, now)
    if wait is not None:
        await reschedule(wait)
        log.info("commenting.post_comment.paused", account_id=account_id, until=wait.isoformat())
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
    except ACCESS_ERRORS as exc:
        await _handle_access_error(
            ctx, exc, campaign_id=campaign_id, account_id=account_id,
            channel_msg_id=channel_msg_id, text=text, reply_to=in_reply_to_message_id,
            channel_ref=target_channel, channel_tg_id=None, monitored_channel_id=None,
        )
        return None
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
    await maybe_continue_thread(
        ctx, campaign_id, channel_msg_id, posted_message_id, thread_depth, post_date_ts
    )
    return posted_message_id


async def maybe_continue_thread(
    ctx: dict,
    campaign_id: int,
    channel_msg_id: int,
    comment_msg_id: Optional[int],
    thread_depth: int,
    post_date_ts: Optional[float] = None,
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
        post_date_ts=post_date_ts,
    )
    get_logger().info(
        "commenting.thread.continue",
        campaign_id=campaign_id,
        in_reply_to=comment_msg_id,
        next_depth=thread_depth + 1,
    )
    return True


# --- аккаунт-центричный мониторинг (у каждого аккаунта свои каналы) -----------
#
# Отличие от campaign-центричного on_new_post: пост в отслеживаемом канале
# комментирует ИМЕННО тот аккаунт, у которого этот канал в работе (эффект
# «сообщества» возникает, когда один канал мониторят несколько аккаунтов — у
# каждого свой слушатель и свой коммент). Discussion-группа берётся из строки
# MonitoredChannel, а не из кампании.
#
# Задел на будущее: on_channel_post уже получает discussion_group_id и id поста,
# поэтому будущая задача «ответить на чужой (человеческий) коммент под постом»
# сможет читать ветку этой же группы и отвечать по теме поста + теме коммента
# (см. параметр in_reply_to, который прокидывается насквозь в post_channel_comment).


def _account_campaign(session, account_id: int):
    """Кампания аккаунта (через CampaignAccount) или (None, None)."""
    link = CampaignAccountRepository(session).get_by_account(account_id)
    if link is None:
        return None, None
    return link.campaign_id, CampaignRepository(session).get(link.campaign_id)


async def on_channel_post(
    ctx: dict,
    account_id: int,
    monitored_channel_id: int,
    channel_msg_id: int,
    in_reply_to: Optional[int] = None,
    thread_depth: int = 0,
    post_date_ts: Optional[float] = None,
) -> int:
    """Пост в канале аккаунта → запланировать ОДИН коммент этим аккаунтом."""
    now = _now(ctx)
    rng = _rng(ctx)
    session_factory = ctx["session_factory"]
    task_queue = _task_queue(ctx)
    log = get_logger()

    with session_factory() as session:
        account = AccountRepository(session).get(account_id)
        if account is None or account.status != "assigned":
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason="not_assigned")
            return 0
        campaign_id, campaign = _account_campaign(session, account_id)
        if campaign is None or not campaign.enabled:
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason="no_campaign")
            return 0
        if not is_within_active_hours(now, campaign):
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason="inactive_hours")
            return 0
        reason = _limit_skip_reason(session, campaign, post_date_ts, now)
        if reason:
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason=reason)
            return 0

        ch = MonitoredChannelRepository(session).get(monitored_channel_id)
        if ch is None or ch.status != "working" or ch.discussion_group_id is None:
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason="channel_not_working")
            return 0
        discussion_group_id = ch.discussion_group_id
        if _blacklisted(session, campaign_id, chat_id=ch.channel_tg_id, ref=ch.channel_ref):
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason="blacklisted")
            return 0

        reply_target = in_reply_to if in_reply_to is not None else channel_msg_id
        provider = ctx.get("llm_provider") or get_provider(campaign.llm_provider)
        context = _thread_context(session, campaign_id, channel_msg_id)
        text, ok = await _generate(ctx, session, campaign, account, provider, context)
        if not ok:
            _log_below_min_words(session, campaign, account_id, channel_msg_id, text, reply_target)
            log.info("commenting.on_channel_post.skip", account_id=account_id, reason="below_min_words")
            return 0
        delay = rng.uniform(campaign.posting_delay_min_sec, campaign.posting_delay_max_sec)

    run_at = now + timedelta(seconds=delay)
    await task_queue.schedule(
        TaskName.COMMENTING_POST_CHANNEL_COMMENT,
        run_at,
        account_id,
        campaign_id,
        discussion_group_id,
        text,
        channel_msg_id,
        reply_target,
        thread_depth=thread_depth,
        post_date_ts=post_date_ts,
    )
    log.info(
        "commenting.on_channel_post.scheduled",
        account_id=account_id, channel_msg_id=channel_msg_id, thread_depth=thread_depth,
    )
    return 1


async def post_channel_comment(
    ctx: dict,
    account_id: int,
    campaign_id: int,
    discussion_group_id: int,
    text: str,
    channel_msg_id: int,
    in_reply_to_message_id: int,
    thread_depth: int = 0,
    post_date_ts: Optional[float] = None,
) -> Optional[int]:
    """Постит коммент аккаунта в discussion-группу его канала (+ governor)."""
    now = _now(ctx)
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    task_queue = _task_queue(ctx)
    log = get_logger()

    async def reschedule(run_at: datetime) -> None:
        await task_queue.schedule(
            TaskName.COMMENTING_POST_CHANNEL_COMMENT,
            run_at,
            account_id,
            campaign_id,
            discussion_group_id,
            text,
            channel_msg_id,
            in_reply_to_message_id,
            thread_depth=thread_depth,
            post_date_ts=post_date_ts,
        )

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is not None:
            reason = _limit_skip_reason(session, campaign, post_date_ts, now)
            if reason:
                log.info("commenting.post_channel_comment.skip", account_id=account_id, reason=reason)
                return None
            wait = limits.pause_wait_until(
                CampaignAccountRepository(session).get(campaign_id, account_id), campaign, now
            )
            if wait is not None:
                await reschedule(wait)
                log.info("commenting.post_channel_comment.paused", account_id=account_id, until=wait.isoformat())
                return None

    if not await _governor(ctx).check_and_reserve(account_id, "comment"):
        await reschedule(now + timedelta(minutes=GOVERNOR_RETRY_MINUTES))
        log.info("commenting.post_channel_comment.rate_limited", account_id=account_id)
        return None

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        wait = limits.claim_post_slot(session, campaign, account_id, now) if campaign else None
    if wait is not None:
        await reschedule(wait)
        log.info("commenting.post_channel_comment.paused", account_id=account_id, until=wait.isoformat())
        return None

    with session_factory() as session:
        mon = next(
            (
                r
                for r in MonitoredChannelRepository(session).list_by_discussion_group(discussion_group_id)
                if r.account_id == account_id
            ),
            None,
        )
        mon_id = mon.id if mon else None
        mon_ref = mon.input_ref if mon else None
        mon_username = mon.channel_ref if mon else None
        mon_tg_id = mon.channel_tg_id if mon else None

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
    except ACCESS_ERRORS as exc:
        await _handle_access_error(
            ctx, exc, campaign_id=campaign_id, account_id=account_id,
            channel_msg_id=channel_msg_id, text=text, reply_to=in_reply_to_message_id,
            channel_ref=mon_ref, channel_tg_id=mon_tg_id, monitored_channel_id=mon_id,
            blacklist_username=mon_username,
        )
        return None
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
        "commenting.post_channel_comment.posted",
        account_id=account_id, posted_message_id=posted_message_id, thread_depth=thread_depth,
    )
    await maybe_continue_channel_thread(
        ctx, account_id, channel_msg_id, posted_message_id, thread_depth, post_date_ts
    )
    return posted_message_id


async def maybe_continue_channel_thread(
    ctx: dict,
    account_id: int,
    channel_msg_id: int,
    comment_msg_id: Optional[int],
    thread_depth: int,
    post_date_ts: Optional[float] = None,
) -> bool:
    """Тред-симуляция для аккаунт-центричной ветки (ответ на свой же коммент)."""
    if comment_msg_id is None or thread_depth >= MAX_THREAD_DEPTH:
        return False
    if _rng(ctx).random() >= THREAD_CONTINUE_PROB:
        return False
    # monitored_channel_id не нужен для повторного матчинга: on_channel_post
    # сам возьмёт discussion-группу по working-каналу аккаунта; но здесь мы уже
    # знаем discussion-группу — переиспользуем on_channel_post по каналу.
    with ctx["session_factory"]() as session:
        working = MonitoredChannelRepository(session).list_working_by_account(account_id)
    if not working:
        return False
    await _task_queue(ctx).enqueue(
        TaskName.COMMENTING_ON_CHANNEL_POST,
        account_id,
        working[0].id,
        channel_msg_id,
        in_reply_to=comment_msg_id,
        thread_depth=thread_depth + 1,
        post_date_ts=post_date_ts,
    )
    get_logger().info(
        "commenting.channel_thread.continue",
        account_id=account_id, in_reply_to=comment_msg_id, next_depth=thread_depth + 1,
    )
    return True
