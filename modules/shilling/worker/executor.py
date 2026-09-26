"""Исполнитель одного шага сценария шиллинга (docs/neuroshilling-spec.md § 5.2).

``execute_step`` отправляет ОДНУ реплику (или ставит реакцию) одним аккаунтом
в целевой чат. Governor лимитирует темп, ``around_telethon_call`` фиксирует
health-инциденты. При бан-подобных ошибках публикуется задача failover
(промпт 4.3) — резервный аккаунт продолжит цепочку.

Инъекции через ctx (для тестов): now, rng, session_factory, client_pool,
task_queue, governor, llm_provider, publisher.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

from core.queue import TaskQueue
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from modules.shilling.repositories import (
    CampaignRepository,
    CampaignTargetRepository,
    ExecutionLogRepository,
    ScenarioRoleRepository,
    ScenarioStepRepository,
)
from modules.shilling.schemas import ExecutionLogCreate
from worker.client_pool import ClientPool
from worker.health import Governor, around_telethon_call

get_logger = structlog.get_logger

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


# --- бан-подобные ошибки → failover ------------------------------------------


def _is_ban_like(exc: Exception) -> bool:
    """PeerFlood / UserBannedInChannel / ChatWriteForbidden → повод для замены.

    Импорт telethon ленивый: класс распознаём по имени, чтобы модуль
    оставался импортируемым без установленного telethon (тесты).
    """
    return type(exc).__name__ in {
        "PeerFloodError",
        "UserBannedInChannelError",
        "ChatWriteForbiddenError",
        "UserIsBlockedError",
    }


# --- задача execute_step -----------------------------------------------------


async def execute_step(
    ctx: dict,
    campaign_id: int,
    target_id: int,
    step_id: int,
    account_id: int,
    thread_msg_id: Optional[int] = None,
) -> Optional[int]:
    """Отправляет один шаг. Возвращает id отправленного сообщения (для чейнинга).

    ``thread_msg_id`` — сообщение, на которое отвечаем (message) или на которое
    ставим реакцию (reaction). Для первого шага цепочки — id поста в обсуждении.
    """
    now = _now(ctx)
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    task_queue = _task_queue(ctx)
    log = get_logger()

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None or not campaign.enabled or campaign.status != "running":
            log.info("shilling.execute_step.skip", campaign_id=campaign_id, reason="not_running")
            return None

        step = ScenarioStepRepository(session).get(step_id)
        if step is None:
            log.info("shilling.execute_step.skip", step_id=step_id, reason="no_step")
            return None

        target = CampaignTargetRepository(session).get(target_id)
        if target is None or target.resolved_chat_id is None:
            log.info("shilling.execute_step.skip", target_id=target_id, reason="target_unresolved")
            return None

        account = AccountRepository(session).get(account_id)
        if account is None or account.status not in {"pool", "assigned"}:
            log.info("shilling.execute_step.skip", account_id=account_id, reason="account_unusable")
            return None

        chat_id = target.resolved_chat_id
        role = ScenarioRoleRepository(session).get(step.role_id) if step.role_id else None
        # Текст готовим ЗДЕСЬ, внутри сессии (нужны step/role/campaign поля).
        step_type = step.step_type
        base_text = step.text or ""
        reaction_emoji = step.reaction_emoji
        role_id = step.role_id
        unique = campaign.unique_messages
        brand = campaign.brand_name
        provider_name = campaign.llm_provider
        role_name = role.name if role else ""
        role_character = role.character if role else None

    # Governor: резервируем слот вне сессии (Redis).
    if not await _governor(ctx).check_and_reserve(account_id, "shilling"):
        run_at = now + timedelta(minutes=GOVERNOR_RETRY_MINUTES)
        await task_queue.schedule(
            TaskName.SHILLING_EXECUTE_STEP,
            run_at,
            campaign_id,
            target_id,
            step_id,
            account_id,
            thread_msg_id=thread_msg_id,
        )
        log.info("shilling.execute_step.rate_limited", account_id=account_id)
        return None

    # Уникализация текста (если включена и это message).
    text = base_text
    if step_type == "message" and unique and base_text:
        provider = ctx.get("llm_provider")
        if provider is None:
            from worker.llm import get_provider

            provider = get_provider(provider_name)
        from modules.shilling.llm import ReplicaRewriter

        text = await ReplicaRewriter(provider).rewrite(
            base_text,
            role_name=role_name,
            role_character=role_character,
            brand_name=brand,
        )

    pool = _pool(ctx)
    client = await pool.get(account_id)
    try:
        if step_type == "reaction":
            sent_id = await _send_reaction(
                client, chat_id, thread_msg_id, reaction_emoji,
                account_id=account_id, session_factory=session_factory,
                publisher=publisher, now=now,
            )
            posted_message_id = None
        else:
            sent = await around_telethon_call(
                lambda: client.send_message(chat_id, text, reply_to=thread_msg_id),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
                now=now,
            )
            posted_message_id = getattr(sent, "id", None)
            sent_id = posted_message_id
    except Exception as exc:
        await pool.release(account_id)
        _log_result(
            session_factory, campaign_id, target_id, account_id, role_id, step_id,
            message_text=text if step_type == "message" else None,
            posted_message_id=None, status="failed", error=type(exc).__name__,
        )
        if _is_ban_like(exc):
            log.warning(
                "shilling.execute_step.ban_like",
                account_id=account_id, error=type(exc).__name__,
            )
            await task_queue.enqueue(
                TaskName.SHILLING_FAILOVER,
                campaign_id, target_id, step_id, account_id,
                thread_msg_id=thread_msg_id,
            )
            return None
        # Прочие ошибки — пусть arq решает про ретрай.
        raise
    else:
        await pool.release(account_id)

    _log_result(
        session_factory, campaign_id, target_id, account_id, role_id, step_id,
        message_text=text if step_type == "message" else None,
        posted_message_id=posted_message_id, status="sent", error=None,
    )
    log.info(
        "shilling.execute_step.sent",
        account_id=account_id, step_id=step_id, posted_message_id=posted_message_id,
    )
    return sent_id


async def _send_reaction(
    client,
    chat_id: int,
    msg_id: Optional[int],
    emoji: Optional[str],
    *,
    account_id: int,
    session_factory,
    publisher,
    now,
):
    """Ставит реакцию на сообщение ``msg_id`` в чате. Возвращает msg_id."""
    if msg_id is None or not emoji:
        return None
    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.types import ReactionEmoji

    await around_telethon_call(
        lambda: client(
            SendReactionRequest(
                peer=chat_id, msg_id=msg_id, reaction=[ReactionEmoji(emoticon=emoji)]
            )
        ),
        account_id=account_id,
        session_factory=session_factory,
        publisher=publisher,
        now=now,
    )
    return msg_id


def _log_result(
    session_factory,
    campaign_id: int,
    target_id: int,
    account_id: int,
    role_id: Optional[int],
    step_id: int,
    *,
    message_text: Optional[str],
    posted_message_id: Optional[int],
    status: str,
    error: Optional[str],
) -> None:
    with session_factory() as session:
        ExecutionLogRepository(session).create(
            ExecutionLogCreate(
                campaign_id=campaign_id,
                target_id=target_id,
                account_id=account_id,
                role_id=role_id,
                step_id=step_id,
                message_text=message_text,
                posted_message_id=posted_message_id,
                status=status,
                error=error,
            )
        )
        session.commit()
