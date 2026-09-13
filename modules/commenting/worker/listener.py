"""Слушатель постов канала в discussion group (PROJECT-STAGES §5, §8.3).

Для каждой enabled-кампании подключается NewMessage-handler в
``discussion_group_id`` через одного из assigned-аккаунтов (round-robin). Handler
ловит ТОЛЬКО посты самого канала (авто-реплей канала в обсуждении) и ставит
``commenting.on_new_post``; комментарии других участников он игнорирует.

Здесь — только «кирпичи» на ОДНУ кампанию (``make_new_post_handler``,
``round_robin_account``). Подключение/отключение слушателей и их реестр живут в
:mod:`modules.commenting.worker.registry` (:class:`ListenerRegistry`): именно он
вызывается из ``worker/main.py`` при старте и реагирует на события
``campaign_lifecycle`` без рестарта воркера.

Тред-симуляция (ответ бота на свой же коммент) реализована в post_comment
(runner.maybe_continue_thread): мы там уже знаем posted_message_id и глубину,
поэтому не полагаемся на повторный матчинг NewMessage.
"""

from __future__ import annotations

from typing import Any, Callable

from core.queue import TaskQueue
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from modules.commenting.repositories import CampaignAccountRepository
from worker.tasks.logging import get_logger


def make_new_post_handler(
    campaign_id: int, task_queue: TaskQueue, *, channel_id: int
) -> Callable[[Any], Any]:
    """Возвращает async-handler: пост канала → enqueue commenting.on_new_post."""

    async def handler(event: Any) -> None:
        message = getattr(event, "message", event)
        # Только сообщения самого канала (не комментарии участников/ботов).
        if getattr(message, "sender_id", None) != channel_id:
            return
        await task_queue.enqueue(
            TaskName.COMMENTING_ON_NEW_POST, campaign_id, message.id
        )
        get_logger().info(
            "commenting.listener.new_post", campaign_id=campaign_id, channel_msg_id=message.id
        )

    return handler


async def round_robin_account(session, campaign_id: int, cursor: dict) -> Any:
    """Следующий assigned-аккаунт кампании по кругу (или None, если таких нет)."""
    links = CampaignAccountRepository(session).list_by_campaign(campaign_id)
    repo = AccountRepository(session)
    assigned = [
        a
        for a in (repo.get(link.account_id) for link in links)
        if a is not None and a.status == "assigned"
    ]
    if not assigned:
        return None
    idx = cursor.get(campaign_id, 0) % len(assigned)
    cursor[campaign_id] = idx + 1
    return assigned[idx]
