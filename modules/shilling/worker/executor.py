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
    CampaignAccountRepository,
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

    Также тригерит failover долгий FloodWaitError (>_FLOOD_WAIT_FAILOVER_SEC):
    ждать 10 минут и дольше бессмысленно — цель в этом окне уже «отработана»
    другим аккаунтом, а наш может схватить ещё больший бан. Короткие
    FloodWait (<5 мин) остаются обычным retry через arq.
    """
    name = type(exc).__name__
    if name in {
        "PeerFloodError",
        "UserBannedInChannelError",
        "ChatWriteForbiddenError",
        "UserIsBlockedError",
    }:
        return True
    if name == "FloodWaitError":
        seconds = getattr(exc, "seconds", 0) or 0
        try:
            return int(seconds) >= _FLOOD_WAIT_FAILOVER_SEC
        except (TypeError, ValueError):
            return False
    return False


_FLOOD_WAIT_FAILOVER_SEC = 300  # ≥5 минут — передаём резервному


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
        # Slow-mode: Telegram говорит «подожди N сек между сообщениями». Если
        # N в пределах разрешённого окна кампании — reschedule, иначе пропуск.
        # Делаем ДО _log_result, чтобы правильный статус пошёл в лог.
        if type(exc).__name__ == "SlowModeWaitError":
            wait = int(getattr(exc, "seconds", 0) or 0)
            if 0 < wait <= int(getattr(campaign, "slow_mode_wait_max_sec", 300)):
                run_at = now + timedelta(seconds=wait + 2)
                await task_queue.schedule(
                    TaskName.SHILLING_EXECUTE_STEP,
                    run_at,
                    campaign_id, target_id, step_id, account_id,
                    thread_msg_id=thread_msg_id,
                )
                _log_result(
                    session_factory, campaign_id, target_id, account_id, role_id, step_id,
                    message_text=None, posted_message_id=None,
                    status="skipped", error=f"slow_mode_wait:{wait}s",
                )
                log.info(
                    "shilling.execute_step.slow_mode_rescheduled",
                    account_id=account_id, wait_sec=wait,
                )
                return None
            # Ждать больше чем разрешено — не ждём, помечаем провалом и уходим.
            _log_result(
                session_factory, campaign_id, target_id, account_id, role_id, step_id,
                message_text=None, posted_message_id=None,
                status="skipped", error=f"slow_mode_too_long:{wait}s",
            )
            log.info(
                "shilling.execute_step.slow_mode_too_long",
                account_id=account_id, wait_sec=wait,
            )
            return None

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

    # Авто-реакция между аккаунтами на только что отправленное сообщение.
    # Отрабатывает только при inter_account_reactions_enabled и
    # step_type == "message" (на реакции реакции ставить бессмысленно).
    # С вероятностью _AUTO_REACTION_P выбираем ДРУГОГО бота кампании и ставим
    # ему эмодзи-реакцию. Промахи логируются и не влияют на основной поток.
    if (
        step_type == "message"
        and posted_message_id is not None
        and getattr(campaign, "inter_account_reactions_enabled", False)
    ):
        try:
            await _maybe_auto_react(
                ctx=ctx,
                campaign_id=campaign_id,
                chat_id=chat_id,
                skip_account_id=account_id,
                posted_message_id=posted_message_id,
                now=now,
            )
        except Exception as exc:  # noqa: BLE001 — вспомогательное действие
            log.warning(
                "shilling.auto_reaction.failed",
                campaign_id=campaign_id, error=repr(exc),
            )

    return sent_id


# Белый список эмодзи для авто-реакций: универсальные, доступны в большинстве
# чатов (включая обычные, без премиум-реакций). Явно безопасный короткий набор.
_AUTO_REACTION_EMOJIS = ("👍", "❤️", "🔥", "😁", "👏", "🤔")
# Вероятность вставки авто-реакции после каждого message-шага. Подбиралось
# на глаз: 35% достаточно часто, чтобы было заметно, и достаточно редко,
# чтобы не превратить тред в стену эмодзи.
_AUTO_REACTION_P = 0.35


async def _maybe_auto_react(
    *,
    ctx,
    campaign_id: int,
    chat_id: int,
    skip_account_id: int,
    posted_message_id: int,
    now,
) -> None:
    """С вероятностью ``_AUTO_REACTION_P`` ставит реакцию от любого другого
    бота кампании (не skip_account_id). Делает один раунд, никаких ретраев."""
    import random as _rnd

    if _rnd.random() > _AUTO_REACTION_P:
        return
    session_factory = ctx["session_factory"]
    with session_factory() as session:
        links = CampaignAccountRepository(session).list_by_campaign(campaign_id)
        candidates = [
            link.account_id
            for link in links
            if link.account_id != skip_account_id and not link.is_reserve
        ]
    if not candidates:
        return
    reactor_id = _rnd.choice(candidates)
    emoji = _rnd.choice(_AUTO_REACTION_EMOJIS)

    # Governor-gate (под отдельным "shilling_reaction" ключом не делаем —
    # используем общий, т.к. это тот же тип активности в клиенте). Если
    # исчерпан — просто не реагируем, без retry.
    if not await _governor(ctx).check_and_reserve(reactor_id, "shilling"):
        return

    pool = _pool(ctx)
    client = await pool.get(reactor_id)
    try:
        await _send_reaction(
            client, chat_id, posted_message_id, emoji,
            account_id=reactor_id, session_factory=session_factory,
            publisher=ctx.get("publisher"), now=now,
        )
    finally:
        await pool.release(reactor_id)
    get_logger().info(
        "shilling.auto_reaction.sent",
        campaign_id=campaign_id, reactor_id=reactor_id, emoji=emoji,
        posted_message_id=posted_message_id,
    )


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
