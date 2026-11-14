"""arq-хендлеры масс-реакций: постановка реакции и tick-раскладчик.

Тонкая обвязка над протестированным ядром (executor + orchestrator):
- ``place_reaction_task`` берёт Telethon-клиент из пула, оборачивает отправку
  в ``around_telethon_call`` (health-инциденты: FloodWait/бан) и делегирует
  логирование/счётчики функции ``place_reaction``;
- ``orchestrator_tick_task`` раскладывает чаты по аккаунтам, авто-финиширует
  кампанию по ``expires_at`` и планирует следующий tick.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.queue import TaskQueue
from core.queue.task_names import TaskName
from modules.mass_reactions.repositories import (
    CampaignAccountRepository,
    CampaignChatRepository,
    CampaignRepository,
)
from modules.mass_reactions.schemas.enums import (
    ChatNotifyMode,
    ChatSourceMode,
    ChatState,
    MassReactionCampaignStatus,
)
from modules.mass_reactions.service import apply_resolution, mark_failed, mark_joined
from modules.mass_reactions.worker.executor import place_reaction
from modules.mass_reactions.worker.orchestrator import assign_pending_chats
from modules.mass_reactions.worker.reaction import send_reaction
from worker.health import around_telethon_call
from worker.tasks.logging import get_logger

# Темп раскладчика: как часто пере-смотреть неназначенные чаты / проверять финиш.
TICK_INTERVAL_SEC = 60


def _task_queue(ctx: dict) -> TaskQueue:
    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


async def place_reaction_task(
    ctx: dict,
    campaign_id: int,
    chat_id: int,
    account_id: int,
    chat_tg_id: int,
    msg_id: int,
    emoji: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Поставить одну реакцию (chat × account × message) через пул + governor."""
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    pool = ctx["client_pool"]
    now = datetime.now(timezone.utc)

    async def send(c_tg: int, m_id: int, emo: str) -> None:
        client = await pool.get(account_id)
        try:
            await around_telethon_call(
                lambda: send_reaction(client, chat_id=c_tg, msg_id=m_id, emoji=emo),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
                now=now,
            )
        finally:
            await pool.release(account_id)

    outcome = await place_reaction(
        session_factory=session_factory,
        send=send,
        campaign_id=campaign_id,
        chat_id=chat_id,
        account_id=account_id,
        chat_tg_id=chat_tg_id,
        msg_id=msg_id,
        emoji=emoji,
        dry_run=dry_run,
    )
    get_logger().info(
        "mass_reactions.place_reaction",
        campaign_id=campaign_id, chat_id=chat_id, account_id=account_id,
        outcome=outcome.value, dry_run=dry_run,
    )
    return {"outcome": outcome.value}


async def resolve_pending_chats(
    ctx: dict, *, campaign_id: int, chat_source_mode: str
) -> int:
    """Резолвит чаты PENDING/JOINING, у которых есть закреплённый аккаунт.

    Через клиент аккаунта получаем entity (chat_tg_id + title); факт подписки
    определяем по режиму источника (по подпискам → уже состоим) и/или успешному
    вступлению при notify_and_join. Итоговое состояние ставит ``apply_resolution``.
    Возвращает число зарезолвленных чатов. Устойчиво к ошибкам per-chat.
    """
    session_factory = ctx["session_factory"]
    pool = ctx["client_pool"]
    by_subs = chat_source_mode == ChatSourceMode.BY_SUBSCRIPTIONS.value

    with session_factory() as session:
        pending = [
            {"id": c.id, "chat_ref": c.chat_ref, "account_id": c.account_id,
             "notify_mode": c.notify_mode}
            for c in CampaignChatRepository(session).list_by_campaign(campaign_id)
            if c.state in (ChatState.PENDING.value, ChatState.JOINING.value)
            and c.account_id is not None
        ]

    resolved = 0
    for chat in pending:
        try:
            client = await pool.get(chat["account_id"])
            try:
                entity = await client.get_entity(chat["chat_ref"])
            finally:
                await pool.release(chat["account_id"])
            chat_tg_id = int(getattr(entity, "id"))
            title = getattr(entity, "title", None)

            subscribed = by_subs
            if not subscribed and chat["notify_mode"] == ChatNotifyMode.NOTIFY_AND_JOIN.value:
                # best-effort вступление; успех → считаем подписанным
                from telethon.tl.functions.channels import JoinChannelRequest

                await client.__call__(JoinChannelRequest(entity))
                subscribed = True

            with session_factory() as session:
                if subscribed:
                    apply_resolution(
                        session, chat["id"], chat_tg_id=chat_tg_id,
                        title=title, subscribed=True,
                    )
                else:
                    apply_resolution(
                        session, chat["id"], chat_tg_id=chat_tg_id,
                        title=title, subscribed=False,
                    )
                session.commit()
            resolved += 1
        except Exception as exc:  # noqa: BLE001 — один чат не роняет резолв
            get_logger().warning(
                "mass_reactions.resolve_failed",
                chat_id=chat["id"], error=repr(exc),
            )
            with session_factory() as session:
                mark_failed(session, chat["id"])
                session.commit()
    return resolved


async def orchestrator_tick_task(ctx: dict, campaign_id: int) -> dict[str, Any]:
    """Раскладка чатов + авто-финиш + планирование следующего tick."""
    session_factory = ctx["session_factory"]
    task_queue = _task_queue(ctx)
    now = datetime.now(timezone.utc)

    with session_factory() as session:
        repo = CampaignRepository(session)
        campaign = repo.get(campaign_id)
        if campaign is None or campaign.status != MassReactionCampaignStatus.RUNNING.value:
            return {"stopped": True}  # не крутимся и не перепланируем

        # Авто-финиш по окну длительности.
        if campaign.expires_at is not None and now >= campaign.expires_at:
            repo.set_status(campaign_id, MassReactionCampaignStatus.FINISHED.value)
            CampaignAccountRepository(session).reset_daily_counters(campaign_id)
            session.commit()
            get_logger().info("mass_reactions.tick.finished", campaign_id=campaign_id)
            return {"finished": True}

        assigned = assign_pending_chats(session, campaign)
        session.commit()
        source_mode = campaign.chat_source_mode  # примитив до закрытия сессии

    # Резолвим назначенные, но ещё не поднятые чаты (chat_tg_id + подписка/join).
    if ctx.get("client_pool") is not None:
        await resolve_pending_chats(
            ctx, campaign_id=campaign_id, chat_source_mode=source_mode
        )

    # Подключаем/отключаем слушателей под текущий набор активных чатов.
    registry = ctx.get("mr_listener_registry")
    if registry is not None:
        await registry.sync(ctx)

    await task_queue.schedule(
        TaskName.MASS_REACTIONS_ORCHESTRATOR_TICK,
        now + timedelta(seconds=TICK_INTERVAL_SEC),
        campaign_id,
    )
    return {"assigned": assigned}
