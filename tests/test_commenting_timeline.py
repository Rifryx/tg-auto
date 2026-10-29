"""Таймлайн кампании: round-trip push_event → recent_events и защита от
async-клиента (регрессия «Таймлайн пуст»).

Баг, который этот тест фиксирует: воркер передавал в push_event АСИНХРОННЫЙ
arq-redis, а push_event синхронный (pipeline().execute()). С async-клиентом
execute() возвращает неожидаемую корутину, и в таймлайн не писалось НИЧЕГО —
диагностика показывала «Таймлайн пуст», хотя listener поднимался. Фикс: воркер
кладёт синхронный клиент в ctx['redis_sync'] и отдаёт его через
registry._timeline_redis.
"""

from __future__ import annotations

from modules.commenting.worker.registry import _timeline_redis
from modules.commenting.worker.timeline import (
    TimelineKind,
    push_event,
    recent_events,
)


class _FakePipeline:
    """Синхронный pipeline: буферизует команды, execute() применяет их разом."""

    def __init__(self, store: dict):
        self._store = store
        self._ops: list = []

    def lpush(self, key, value):
        self._ops.append(("lpush", key, value))
        return self

    def ltrim(self, key, start, stop):
        self._ops.append(("ltrim", key, start, stop))
        return self

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))
        return self

    def execute(self):
        for op in self._ops:
            if op[0] == "lpush":
                self._store.setdefault(op[1], []).insert(0, op[2])
            elif op[0] == "ltrim":
                _, key, start, stop = op
                self._store[key] = self._store.get(key, [])[start : stop + 1]
        self._ops = []
        return []


class _FakeSyncRedis:
    """Минимальный синхронный redis под lpush/ltrim/expire/lrange + pipeline."""

    def __init__(self):
        self.store: dict = {}

    def pipeline(self):
        return _FakePipeline(self.store)

    def lrange(self, key, start, stop):
        return self.store.get(key, [])[start : stop + 1]


class _AsyncPipeline:
    """Имитация async-клиента: execute() — корутина (как у redis.asyncio)."""

    def lpush(self, *a, **k):
        return self

    def ltrim(self, *a, **k):
        return self

    def expire(self, *a, **k):
        return self

    async def execute(self):  # корутина — её НИКТО не ждёт в sync push_event
        raise AssertionError("не должно выполниться синхронно")


class _AsyncRedis:
    def pipeline(self):
        return _AsyncPipeline()


def test_timeline_round_trip_with_sync_client():
    r = _FakeSyncRedis()
    push_event(r, 42, TimelineKind.LISTENER_ONLINE, "listener up", meta={"account_id": 1})
    push_event(r, 42, TimelineKind.POST_RECEIVED, "пост пойман", meta={"channel_msg_id": 7})

    events = recent_events(r, 42, limit=10)
    # recent_events отдаёт сначала новые.
    assert [e.kind for e in events] == ["post_received", "listener_online"]
    assert events[0].message == "пост пойман"
    assert events[0].meta == {"channel_msg_id": 7}
    # Другая кампания — пусто (ключи не пересекаются).
    assert recent_events(r, 99) == []


def test_push_event_with_async_client_does_not_raise_and_writes_nothing():
    """Async-клиент (как arq-redis) — push_event не падает, но и не пишет.

    Это и есть корень «Таймлайн пуст»: с таким клиентом execute() — корутина,
    поэтому воркер ОБЯЗАН использовать синхронный ctx['redis_sync']."""
    import warnings

    ar = _AsyncRedis()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # "coroutine was never awaited"
        push_event(ar, 1, TimelineKind.POST_QUEUED, "в очередь")
    # Читаем синхронным фейком — ничего не записалось.
    assert recent_events(_FakeSyncRedis(), 1) == []


def test_timeline_redis_prefers_sync_client():
    sync = _FakeSyncRedis()
    # ctx['redis'] (async arq) игнорируется — берём ctx['redis_sync'].
    ctx = {"redis": object(), "redis_sync": sync}
    assert _timeline_redis(ctx) is sync
    # Нет sync-клиента (тесты/дев) → None → push_event просто no-op.
    assert _timeline_redis({"redis": object()}) is None
