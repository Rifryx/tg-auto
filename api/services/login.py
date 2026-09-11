"""Оркестрация логина на стороне API (PROJECT-STAGES §11).

API сам НЕ логинится (никакого Telethon): команды уходят в очередь, а состояние
приходит обратно через Redis pub/sub канал ``login``. :class:`LoginEventHub` —
единственная точка подписки процесса на этот канал: держит одну подписку,
кэширует последнее состояние по аккаунту (с меткой времени получения) и
раздаёт события всем SSE-подписчикам конкретного аккаунта.

Полезная нагрузка события (от воркера): ``{account_id, state, reason?}``.
Метку времени добавляет хаб в момент получения — воркер её не присылает.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

import redis.asyncio as aioredis

from core.config import get_settings

LOGIN_CHANNEL = "login"


class LoginEventHub:
    """Подписка на Redis-канал ``login`` + кэш состояний + fan-out для SSE."""

    def __init__(self, redis_url: str, channel: str = LOGIN_CHANNEL) -> None:
        self._redis_url = redis_url
        self._channel = channel
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Any = None
        self._task: Optional[asyncio.Task] = None
        self._started = False
        self._lock = asyncio.Lock()
        self._cache: dict[int, dict[str, Any]] = {}
        self._subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)

    async def ensure_started(self) -> None:
        """Идемпотентно поднимает подписку и фоновый слушатель (в текущем loop)."""
        if self._started:
            return
        async with self._lock:
            if self._started:
                return
            self._redis = aioredis.from_url(self._redis_url)
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(self._channel)
            self._task = asyncio.create_task(self._listen())
            self._started = True

    async def _listen(self) -> None:
        assert self._pubsub is not None
        async for message in self._pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if isinstance(data, (bytes, bytearray)):
                data = data.decode()
            try:
                payload = json.loads(data)
            except (TypeError, ValueError):
                continue
            self._handle(payload)

    def _handle(self, payload: dict[str, Any]) -> None:
        account_id = payload.get("account_id")
        if account_id is None:
            return
        entry = {
            "account_id": account_id,
            "state": payload.get("state"),
            "reason": payload.get("reason"),
            "updated_at": datetime.now(timezone.utc),
        }
        self._cache[account_id] = entry
        for queue in list(self._subscribers.get(account_id, ())):
            queue.put_nowait(entry)

    def get_state(self, account_id: int) -> Optional[dict[str, Any]]:
        return self._cache.get(account_id)

    def subscribe(self, account_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[account_id].add(queue)
        return queue

    def unsubscribe(self, account_id: int, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(account_id)
        if subs is None:
            return
        subs.discard(queue)
        if not subs:
            self._subscribers.pop(account_id, None)

    async def stop(self) -> None:
        """Корректно гасит слушатель и закрывает соединения (shutdown/тесты).

        Все шаги защищены таймаутом: закрытие pub/sub-соединения не должно
        подвешивать shutdown приложения.
        """
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


_hub: Optional[LoginEventHub] = None


def get_login_hub() -> LoginEventHub:
    """Провайдер процесс-синглтона хаба (переопределяется в тестах)."""
    global _hub
    if _hub is None:
        _hub = LoginEventHub(get_settings().redis_url)
    return _hub
