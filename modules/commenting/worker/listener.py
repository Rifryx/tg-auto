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

import random
from typing import Any, Callable, Iterable, Optional

from core.queue import TaskQueue
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from modules.commenting.repositories import CampaignAccountRepository
from worker.tasks.logging import get_logger


def _passes_post_filter(
    text: Optional[str],
    *,
    mode: str,
    keywords: Iterable[str],
    probability_percent: int,
    rng: random.Random,
) -> bool:
    """Пост проходит фильтр отбора (§ Этап 2, post_selection_mode).

    * ``all``           → всегда True.
    * ``keywords``      → в тексте есть хотя бы одно ключевое слово
      (case-insensitive substring). Пустой список ключей → False (иначе
      keywords ничем не отличался бы от all).
    * ``probability``   → коин-флип 0..99 < probability_percent.
    """

    if mode == "all":
        return True
    if mode == "keywords":
        haystack = (text or "").lower()
        needles = [k.lower() for k in keywords if k]
        if not needles:
            return False
        return any(k in haystack for k in needles)
    if mode == "probability":
        pct = max(0, min(100, probability_percent))
        return rng.randrange(100) < pct
    # Неизвестный режим — не блокируем поток (безопасный дефолт).
    return True


def make_new_post_handler(
    campaign_id: int,
    task_queue: TaskQueue,
    *,
    channel_id: int,
    session_factory: Optional[Callable[[], Any]] = None,
    rng: Optional[random.Random] = None,
) -> Callable[[Any], Any]:
    """Возвращает async-handler: пост канала → enqueue commenting.on_new_post.

    При наличии ``session_factory`` handler читает актуальную конфигурацию
    кампании (post_selection_mode / keywords / probability_percent) и
    отсеивает посты ещё ДО постановки задачи в очередь. Так работник не
    получает шум для игнорируемых постов, а логика фильтра остаётся в одном
    месте.
    """

    _rng = rng or random.Random()

    async def handler(event: Any) -> None:
        message = getattr(event, "message", event)
        # Только сообщения самого канала (не комментарии участников/ботов).
        if getattr(message, "sender_id", None) != channel_id:
            return

        if session_factory is not None:
            # Локальный импорт: у registry свой __init__ порядок, избегаем цикла.
            from modules.commenting.repositories import CampaignRepository

            with session_factory() as session:
                campaign = CampaignRepository(session).get(campaign_id)
                if campaign is None or not campaign.enabled:
                    return
                text = getattr(message, "message", None) or getattr(message, "text", None)
                if not _passes_post_filter(
                    text,
                    mode=campaign.post_selection_mode,
                    keywords=campaign.keywords or [],
                    probability_percent=campaign.probability_percent,
                    rng=_rng,
                ):
                    get_logger().info(
                        "commenting.listener.filtered",
                        campaign_id=campaign_id,
                        channel_msg_id=message.id,
                        mode=campaign.post_selection_mode,
                    )
                    return

        await task_queue.enqueue(
            TaskName.COMMENTING_ON_NEW_POST, campaign_id, message.id
        )
        get_logger().info(
            "commenting.listener.new_post", campaign_id=campaign_id, channel_msg_id=message.id
        )

    return handler


def make_channel_post_handler(
    account_id: int,
    monitored_channel_id: int,
    task_queue: TaskQueue,
    *,
    channel_tg_id: int,
) -> Callable[[Any], Any]:
    """Handler для аккаунт-центричного мониторинга: пост канала → on_channel_post.

    Ловит ТОЛЬКО авто-реплей самого канала в discussion-группе (sender_id ==
    channel_tg_id) и ставит ``commenting.on_channel_post`` для аккаунта-владельца.
    Человеческие комментарии игнорируются — но именно здесь будущая фича «ответить
    на чей-то коммент» подключит свою ветку (у нас есть и группа, и id поста).
    """

    async def handler(event: Any) -> None:
        message = getattr(event, "message", event)
        if getattr(message, "sender_id", None) != channel_tg_id:
            return
        await task_queue.enqueue(
            TaskName.COMMENTING_ON_CHANNEL_POST,
            account_id,
            monitored_channel_id,
            message.id,
        )
        get_logger().info(
            "commenting.channel_listener.new_post",
            account_id=account_id,
            monitored_channel_id=monitored_channel_id,
            channel_msg_id=message.id,
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
