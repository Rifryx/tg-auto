"""Провайдеры очереди задач и pub/sub для API-слоя.

API кладёт задачи ТОЛЬКО через :class:`TaskQueue` (никакого прямого Telethon).
В тестах провайдеры переопределяются spy-объектами через ``dependency_overrides``.
"""

from __future__ import annotations

from typing import Optional

from core.queue import TaskQueue
from core.queue.publisher import Publisher


def get_task_queue() -> TaskQueue:
    # Без явного redis TaskQueue лениво поднимет пул из core.config (REDIS_URL).
    return TaskQueue()


def get_publisher() -> Optional[Publisher]:
    # Публикация статус-событий необязательна для CRUD; по умолчанию отключена.
    return None
