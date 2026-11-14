"""Реестр слушателей чатов масс-реакций — живое звено исполнения.

На каждый активный чат вешаем Telethon ``events.NewMessage`` на клиенте
закреплённого аккаунта; хендлер (``make_chat_message_handler``) фильтрует
«живых людей», считает «каждое N-е» по чату и ставит задачу на реакцию.

Паттерн повторяет commenting.ListenerRegistry: клиент берём из ``client_pool``
и НЕ возвращаем (event-handler держит соединение). ``sync`` сверяет набор
подключённых чатов с тем, что должно слушаться (running-кампании, active-чаты с
резолвнутым ``chat_tg_id`` и назначенным аккаунтом): новое — подключает,
лишнее — отключает. Вызывается на старте воркера и из orchestrator_tick.

Чистые замыкания (счётчик/постановка задачи) вынесены в helpers и покрыты
тестами; сама attach/detach-обвязка Telethon проверяется на живом воркере.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from core.queue import TaskQueue
from core.queue.task_names import TaskName
from modules.mass_reactions.repositories import (
    CampaignChatRepository,
    CampaignRepository,
)
from modules.mass_reactions.schemas.enums import (
    ChatState,
    MassReactionCampaignStatus,
)
from modules.mass_reactions.worker.listener import make_chat_message_handler
from worker.tasks.logging import get_logger


@dataclass
class _Attached:
    client: Any
    handler: Any
    event: Any
    account_id: int


def _task_queue(ctx: dict) -> TaskQueue:
    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


def make_counter(session_factory: Callable[[], Any], chat_id: int) -> Callable[[], int]:
    """increment_counter для слушателя: атомарный +1 к счётчику чата в своей
    короткой сессии (возвращает новое значение)."""

    def _inc() -> int:
        with session_factory() as session:
            n = CampaignChatRepository(session).bump_counter(chat_id)
            session.commit()
            return n

    return _inc


def make_enqueue(
    task_queue: TaskQueue,
    *,
    campaign_id: int,
    chat_id: int,
    account_id: int,
    chat_tg_id: int,
    dry_run: bool,
) -> Callable[[int, str], Awaitable[None]]:
    """enqueue_reaction: ставит задачу mass_reactions.place_reaction."""

    async def _enqueue(msg_id: int, emoji: str) -> None:
        await task_queue.enqueue(
            TaskName.MASS_REACTIONS_PLACE_REACTION,
            campaign_id, chat_id, account_id, chat_tg_id, msg_id, emoji, dry_run,
        )

    return _enqueue


def _listenable(session_factory: Callable[[], Any]) -> list[dict]:
    """Чаты, которые ДОЛЖНЫ слушаться: running-кампания, active-чат, есть
    chat_tg_id и назначенный аккаунт. Возвращает плоские dict'ы (без ORM вне
    сессии)."""
    out: list[dict] = []
    with session_factory() as session:
        running = {
            c.id: c
            for c in CampaignRepository(session).list_by_status(
                MassReactionCampaignStatus.RUNNING.value
            )
        }
        for cid, camp in running.items():
            for chat in CampaignChatRepository(session).list_by_campaign(cid):
                if (
                    chat.state == ChatState.ACTIVE.value
                    and chat.chat_tg_id is not None
                    and chat.account_id is not None
                ):
                    out.append(
                        {
                            "chat_id": chat.id,
                            "campaign_id": cid,
                            "account_id": chat.account_id,
                            "chat_tg_id": chat.chat_tg_id,
                            "emojis": list(camp.reaction_emojis),
                            "reaction_strategy": camp.reaction_strategy,
                            "every_n_message": camp.every_n_message,
                            "probability_percent": camp.probability_percent,
                            "skip_older_than_days": camp.skip_messages_older_than_days,
                        }
                    )
    return out


class ReactionListenerRegistry:
    def __init__(self) -> None:
        self._attached: dict[int, _Attached] = {}  # chat_id → _Attached
        self._lock = asyncio.Lock()

    def active_chats(self) -> list[int]:
        return sorted(self._attached)

    async def sync(self, ctx: dict) -> dict[str, int]:
        """Сверяет подключённые слушатели с тем, что должно слушаться.

        Отказоустойчиво: сбой выборки (напр. БД недоступна на старте) логируем и
        выходим — один подсистемный сбой не должен ронять старт воркера.
        """
        session_factory = ctx["session_factory"]
        try:
            want = {d["chat_id"]: d for d in _listenable(session_factory)}
        except Exception as exc:  # noqa: BLE001
            get_logger().warning("mass_reactions.listener.sync_failed", error=repr(exc))
            return {"attached": 0, "detached": 0}
        attached_count = 0
        detached_count = 0
        async with self._lock:
            # Отключаем лишние.
            for chat_id in list(self._attached):
                if chat_id not in want:
                    await self._detach(chat_id)
                    detached_count += 1
            # Подключаем новые.
            for chat_id, spec in want.items():
                if chat_id in self._attached:
                    continue
                if await self._attach(ctx, spec):
                    attached_count += 1
        get_logger().info(
            "mass_reactions.listener.sync",
            attached=attached_count, detached=detached_count,
            total=len(self._attached),
        )
        return {"attached": attached_count, "detached": detached_count}

    async def _attach(self, ctx: dict, spec: dict) -> bool:
        from telethon import events

        session_factory = ctx["session_factory"]
        pool = ctx["client_pool"]
        task_queue = _task_queue(ctx)
        dry_run = bool(ctx.get("dry_run", False))
        try:
            client = await pool.get(spec["account_id"])
            handler = make_chat_message_handler(
                campaign_id=spec["campaign_id"],
                chat_id=spec["chat_id"],
                account_id=spec["account_id"],
                every_n_message=spec["every_n_message"],
                probability_percent=spec["probability_percent"],
                skip_older_than_days=spec["skip_older_than_days"],
                emojis=spec["emojis"],
                reaction_strategy=spec["reaction_strategy"],
                increment_counter=make_counter(session_factory, spec["chat_id"]),
                enqueue_reaction=make_enqueue(
                    task_queue,
                    campaign_id=spec["campaign_id"],
                    chat_id=spec["chat_id"],
                    account_id=spec["account_id"],
                    chat_tg_id=spec["chat_tg_id"],
                    dry_run=dry_run,
                ),
                redis=ctx.get("redis"),
            )
            event = events.NewMessage(chats=spec["chat_tg_id"])
            client.add_event_handler(handler, event)
            self._attached[spec["chat_id"]] = _Attached(
                client=client, handler=handler, event=event,
                account_id=spec["account_id"],
            )
            return True
        except Exception as exc:  # noqa: BLE001 — один чат не должен ронять sync
            get_logger().warning(
                "mass_reactions.listener.attach_failed",
                chat_id=spec["chat_id"], error=repr(exc),
            )
            return False

    async def _detach(self, chat_id: int) -> None:
        att = self._attached.pop(chat_id, None)
        if att is None:
            return
        try:
            att.client.remove_event_handler(att.handler, att.event)
        except Exception as exc:  # noqa: BLE001
            get_logger().warning(
                "mass_reactions.listener.detach_failed",
                chat_id=chat_id, error=repr(exc),
            )
