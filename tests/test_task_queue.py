from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from arq.connections import RedisSettings
from cryptography.fernet import Fernet

from core.queue import QueueName, TaskName, TaskQueue, close_task_pool

# Тестовый Redis: локально — сервис redis_test из docker-compose (6380),
# в CI переопределяется через TEST_REDIS_URL. Отдельная БД (/1), чтобы не мешать.
REDIS_DSN = os.getenv("TEST_REDIS_URL", "redis://localhost:6380/1")


def _make_worker(functions, *, burst=True, poll_delay=0.05):
    # Импорт внутри, чтобы arq тянулся только когда реально нужен воркер.
    from arq.worker import Worker

    return Worker(
        functions=functions,
        redis_settings=RedisSettings.from_dsn(REDIS_DSN),
        queue_name=QueueName.DEFAULT.value,
        burst=burst,
        poll_delay=poll_delay,
        handle_signals=False,
    )


@pytest_asyncio.fixture
async def tq(monkeypatch):
    # Конфиг валиден в DEV_MODE; Redis-DSN берётся из ENV через core.config.
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("REDIS_URL", REDIS_DSN)

    from core.config import get_settings

    get_settings.cache_clear()
    await close_task_pool()

    client = aioredis.from_url(REDIS_DSN)
    await client.flushdb()

    queue = TaskQueue()  # singleton-пул из core.config
    try:
        yield queue
    finally:
        await close_task_pool()
        await client.flushdb()
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_enqueue_is_picked_up_by_worker(tq):
    got = {}
    done = asyncio.Event()

    async def handler(ctx, *args, **kwargs):
        got["args"] = args
        got["kwargs"] = kwargs
        done.set()

    from arq.worker import func

    job_id = await tq.enqueue(TaskName.WARMING_TICK, 42, account_id=7)
    assert isinstance(job_id, str)

    worker = _make_worker([func(handler, name=TaskName.WARMING_TICK.value)])
    await asyncio.wait_for(worker.async_run(), timeout=10)

    assert done.is_set()
    assert got["args"] == (42,)
    assert got["kwargs"] == {"account_id": 7}


@pytest.mark.asyncio
async def test_schedule_runs_around_run_at(tq):
    fired_at = {}
    done = asyncio.Event()

    async def handler(ctx, *args, **kwargs):
        fired_at["t"] = asyncio.get_running_loop().time()
        done.set()

    from arq.worker import func

    t0 = asyncio.get_running_loop().time()
    run_at = datetime.now(timezone.utc) + timedelta(seconds=2)
    await tq.schedule(TaskName.WARMING_TICK, run_at)

    worker = _make_worker([func(handler, name=TaskName.WARMING_TICK.value)])
    await asyncio.wait_for(worker.async_run(), timeout=10)

    assert done.is_set()
    elapsed = fired_at["t"] - t0
    assert 1.5 <= elapsed <= 2.5, f"elapsed={elapsed:.3f}s (ожидалось ~2s ±0.5)"


@pytest.mark.asyncio
async def test_unknown_task_name_raises_without_touching_redis(tq):
    client = aioredis.from_url(REDIS_DSN)
    try:
        assert await client.dbsize() == 0

        with pytest.raises(ValueError):
            await tq.enqueue("account.does_not_exist", 1, foo="bar")

        # в Redis ничего не улетело
        assert await client.dbsize() == 0
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_cancel_scheduled_prevents_execution(tq):
    done = asyncio.Event()

    async def handler(ctx, *args, **kwargs):
        done.set()

    from arq.worker import func

    run_at = datetime.now(timezone.utc) + timedelta(seconds=2)
    job_id = await tq.schedule(TaskName.WARMING_TICK, run_at)

    assert await tq.cancel(job_id) is True

    # очередь пуста → burst-воркер завершится сразу и задачу не выполнит
    worker = _make_worker([func(handler, name=TaskName.WARMING_TICK.value)])
    await asyncio.wait_for(worker.async_run(), timeout=5)

    assert not done.is_set()


@pytest.mark.asyncio
async def test_high_queue_reserved_but_unused():
    # 'high' заведена, но пока не используется по умолчанию
    assert QueueName.HIGH.value == "high"
    assert TaskQueue()._queue is QueueName.DEFAULT
