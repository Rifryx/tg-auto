"""Глобальный поток доменных событий для дашборда (PROJECT-STAGES §10; аудит #9).

Промпт 23 публикует ``account_status`` / ``health_alert`` / ``warming_progress``
в Redis pub/sub. :class:`MonitoringEventHub` — единственная точка подписки
API-процесса на эти каналы: держит одну подписку и раздаёт КАЖДОЕ событие всем
SSE-подписчикам дашборда (в отличие от :class:`LoginEventHub`, который фильтрует
по аккаунту). Так фронт мгновенно обновляет алерты, не дожидаясь refetch.

Образец — :class:`api.services.login.LoginEventHub`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

import redis.asyncio as aioredis

from core.config import get_settings

# Каналы, которые публикует воркер/state machine (промпт 23).
MONITORING_CHANNELS = ("account_status", "health_alert", "warming_progress")


class MonitoringEventHub:
    """Подписка на доменные каналы + глобальный fan-out для SSE дашборда."""

    def __init__(
        self, redis_url: str, channels: tuple[str, ...] = MONITORING_CHANNELS
    ) -> None:
        self._redis_url = redis_url
        self._channels = tuple(channels)
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Any = None
        self._task: Optional[asyncio.Task] = None
        self._started = False
        self._lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue] = set()

    async def ensure_started(self) -> None:
        """Идемпотентно поднимает подписку и фоновый слушатель (в текущем loop)."""
        if self._started:
            return
        async with self._lock:
            if self._started:
                return
            self._redis = aioredis.from_url(self._redis_url)
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(*self._channels)
            self._task = asyncio.create_task(self._listen())
            self._started = True

    async def _listen(self) -> None:
        assert self._pubsub is not None
        async for message in self._pubsub.listen():
            if message.get("type") != "message":
                continue
            channel = message.get("channel")
            if isinstance(channel, (bytes, bytearray)):
                channel = channel.decode()
            data = message.get("data")
            if isinstance(data, (bytes, bytearray)):
                data = data.decode()
            try:
                payload = json.loads(data)
            except (TypeError, ValueError):
                continue
            self._fanout(channel, payload)

    def _fanout(self, channel: Optional[str], payload: dict[str, Any]) -> None:
        entry = {"type": channel, **payload}
        for queue in list(self._subscribers):
            queue.put_nowait(entry)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
            self._task = None
        if self._pubsub is not None:
            try:
                await asyncio.wait_for(self._pubsub.aclose(), timeout=2.0)
            except Exception:
                pass
            self._pubsub = None
        if self._redis is not None:
            try:
                await asyncio.wait_for(self._redis.aclose(), timeout=2.0)
            except Exception:
                pass
            self._redis = None
        self._started = False


_hub: Optional[MonitoringEventHub] = None


def get_monitoring_hub() -> MonitoringEventHub:
    """Провайдер процесс-синглтона хаба (переопределяется в тестах)."""
    global _hub
    if _hub is None:
        _hub = MonitoringEventHub(get_settings().redis_url)
    return _hub
