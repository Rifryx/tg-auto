"""Минимальный pub/sub-паблишер поверх Redis.

Только публикация событий домена в каналы Redis. Очередь задач (arq) — это
отдельный этап (см. PROJECT-STAGES §2) и здесь намеренно не реализуется.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class Publisher(Protocol):
    """Контракт паблишера: опубликовать payload в канал."""

    def publish(self, channel: str, payload: Mapping[str, Any]) -> None: ...


class RedisPublisher:
    """Публикует JSON-payload в Redis-канал.

    Клиент передаётся снаружи (``redis.Redis`` или совместимый, напр. fakeredis),
    поэтому модуль не тянет жёсткую зависимость на конкретный redis-клиент.

    ВАЖНО: ``publish`` синхронный, поэтому клиент должен быть СИНХРОННЫМ
    (``redis.Redis``). Асинхронный клиент (``redis.asyncio``/arq) вернул бы
    неожиданную корутину, и публикация тихо не произошла бы — используйте
    :func:`build_redis_publisher`, чтобы получить публикатор на синхронном клиенте.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def publish(self, channel: str, payload: Mapping[str, Any]) -> None:
        self._client.publish(channel, json.dumps(payload, default=str))


def build_redis_publisher(redis_url: str) -> RedisPublisher:
    """Публикатор поверх СИНХРОННОГО redis-клиента (один и тот же для API и воркера).

    ``redis`` — рантайм-зависимость (см. pyproject); импорт локальный, чтобы
    ``core.queue.publisher`` оставался импортируемым и без установленного пакета
    в средах, где публикация не нужна.
    """
    import redis  # sync-клиент

    return RedisPublisher(redis.Redis.from_url(redis_url))
