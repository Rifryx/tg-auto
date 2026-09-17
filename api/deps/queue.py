"""Провайдеры очереди задач и pub/sub для API-слоя.

API кладёт задачи ТОЛЬКО через :class:`TaskQueue` (никакого прямого Telethon).
В тестах провайдеры переопределяются spy-объектами через ``dependency_overrides``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from core.config import get_settings
from core.queue import TaskQueue
from core.queue.publisher import Publisher, build_redis_publisher


def get_task_queue() -> TaskQueue:
    # Без явного redis TaskQueue лениво поднимет пул из core.config (REDIS_URL).
    return TaskQueue()


@lru_cache
def _publisher() -> Publisher:
    # Тот же класс публикатора, что и у воркера, на СИНХРОННОМ redis-клиенте,
    # подключённый к тому же Redis (REDIS_URL). Кэшируется на процесс.
    return build_redis_publisher(get_settings().redis_url)


def get_publisher() -> Optional[Publisher]:
    """Реальный публикатор статус-событий для переходов, инициированных из API.

    Раньше возвращал ``None`` → state machine, вызываемая из API-роутов
    (attach/detach, retire, acknowledge_ban), ничего не публиковала в
    ``account_status`` (аудит #9). Теперь у неё есть настоящий публикатор, и
    события публикуются ТАК ЖЕ, как при переходах из воркера. Вторую публикацию
    сверху НЕ добавляем — публикует сама state machine после commit'а.
    """
    return _publisher()
