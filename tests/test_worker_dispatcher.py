from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from arq.connections import RedisSettings, create_pool
from arq.jobs import Job
from arq.worker import Worker, func
from cryptography.fernet import Fernet
from structlog.testing import capture_logs

import core.queue as core_queue
from core.enums import AccountStatus, Initiator
from core.queue import TaskName, TaskQueue
from core.repositories.account import AccountRepository
from core.schemas.account import AccountCreate
from worker.tasks import (
    FloodWaitError,
    cooldown_return,
    registered_names,
    task,
    warming_initial_start,
)

REDIS_DSN = os.getenv("TEST_REDIS_URL_WORKER", "redis://localhost:6380/2")

_PHONE = iter(range(40_000_000_000, 40_000_100_000))


def _make_account(session, status: AccountStatus, **fields) -> "object":
    repo = AccountRepository(session)
    acc = repo.create(
        AccountCreate(
            phone=f"+{next(_PHONE)}",
            session_enc=b"enc",
            device_model="Samsung SM-S928B",
            system_version="SDK 34",
            app_version="10.14.5 (5218)",
            lang_code="uk",
            system_lang_code="uk-UA",
        )
    )
    if status is not AccountStatus.CREATED:
        acc.status = status.value
    for k, v in fields.items():
        setattr(acc, k, v)
    session.flush()
    return acc


class _KeepOpen:
    """session_factory для тестов: отдаёт живую сессию и не закрывает её."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


# --------------------------------------------------------------------------- #
# 1. Все задачи зарегистрированы и видны в логах при старте.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_startup_logs_all_registered_functions(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("REDIS_URL", REDIS_DSN)

    from core.config import get_settings

    get_settings.cache_clear()
    import worker.main as worker_main

    # Тест про логирование регистрации: подключение слушателей и фоновую подписку
    # изолируем (без БД/Redis), чтобы startup дошёл до лог-события.
    class _FakeRegistry:
        async def load_all(self, ctx):
            return []

        def active(self):
            return []

    class _FakeLifecycle:
        def __init__(self, *a, **k):
            pass

        async def run(self):
            return None

    monkeypatch.setattr(worker_main, "ListenerRegistry", _FakeRegistry)
    monkeypatch.setattr(worker_main, "CampaignLifecycleListener", _FakeLifecycle)
    # Аккаунт-центричные слушатели каналов изолируем тем же способом.
    monkeypatch.setattr(worker_main, "ChannelListenerRegistry", _FakeRegistry)
    monkeypatch.setattr(worker_main, "ChannelLifecycleListener", _FakeLifecycle)

    ctx: dict = {"redis": object()}
    with capture_logs() as logs:
        await worker_main.startup(ctx)

    # фоновые задачи гасим, чтобы не текли между тестами
    for key in ("campaign_lifecycle_task", "channel_lifecycle_task"):
        task = ctx.get(key)
        if task is not None:
            task.cancel()

    startup_events = [e for e in logs if e["event"] == "worker.startup"]
    assert startup_events, "нет события worker.startup"
    logged = set(startup_events[0]["functions"]) | set(startup_events[0]["cron_jobs"])
    assert logged == {t.value for t in TaskName}
    # cron отдельно
    assert TaskName.WARMING_MAINTENANCE_SCHEDULER.value in startup_events[0]["cron_jobs"]

    get_settings.cache_clear()


def test_registered_names_cover_full_task_list():
    assert set(registered_names()) == {t.value for t in TaskName}


# --------------------------------------------------------------------------- #
# 2. health.cooldown_return возвращает истёкшие аккаунты в previous_status.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_cooldown_return_returns_expired_accounts(session):
    now = datetime.now(timezone.utc)

    from_pool = _make_account(
        session,
        AccountStatus.COOLDOWN,
        previous_status=AccountStatus.POOL.value,
        cooldown_until=now - timedelta(minutes=5),
    )
    from_assigned = _make_account(
        session,
        AccountStatus.COOLDOWN,
        previous_status=AccountStatus.ASSIGNED.value,
        cooldown_until=now - timedelta(minutes=5),
        assigned_container_type="commenting",
        assigned_container_id=7,
    )
    not_expired = _make_account(
        session,
        AccountStatus.COOLDOWN,
        previous_status=AccountStatus.POOL.value,
        cooldown_until=now + timedelta(hours=1),
    )

    ctx = {"session_factory": lambda: _KeepOpen(session), "publisher": None}
    returned = await cooldown_return(ctx)

    assert set(returned) == {from_pool.id, from_assigned.id}

    repo = AccountRepository(session)
    assert repo.get(from_pool.id).status == AccountStatus.POOL.value
    assert repo.get(from_assigned.id).status == AccountStatus.ASSIGNED.value
    assert repo.get(not_expired.id).status == AccountStatus.COOLDOWN.value


# --------------------------------------------------------------------------- #
# 3. Заглушка -> NotImplementedError -> arq делает 3 попытки -> failed.
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def arq_pool():
    client = aioredis.from_url(REDIS_DSN)
    await client.flushdb()
    pool = await create_pool(RedisSettings.from_dsn(REDIS_DSN))
    try:
        yield pool
    finally:
        await pool.aclose()
        await client.flushdb()
        await client.aclose()


@pytest.mark.asyncio
async def test_stub_retries_three_times_then_failed(arq_pool):
    calls: list[int] = []

    async def failing(ctx, *args, **kwargs):
        calls.append(1)
        raise NotImplementedError("stub")

    name = TaskName.ACCOUNT_RETIRE.value
    wrapped = func(task(name)(failing), name=name, max_tries=3)

    tq = TaskQueue(redis=arq_pool)
    job_id = await tq.enqueue(TaskName.ACCOUNT_RETIRE)

    worker = Worker(
        functions=[wrapped],
        redis_pool=arq_pool,
        queue_name="default",
        burst=True,
        poll_delay=0.05,
        handle_signals=False,
    )
    await asyncio.wait_for(worker.async_run(), timeout=15)

    assert len(calls) == 3

    info = await Job(job_id, redis=arq_pool).result_info()
    assert info is not None
    assert info.success is False


# --------------------------------------------------------------------------- #
# 4. FloodWaitError(15) -> перепланирование на now+15s через TaskQueue.schedule.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_flood_wait_reschedules_via_task_queue(monkeypatch):
    spy: list[dict] = []

    async def fake_schedule(self, task_name, run_at, *args, **kwargs):
        spy.append(
            {"name": task_name, "run_at": run_at, "args": args, "kwargs": kwargs}
        )
        return "scheduled-job-id"

    monkeypatch.setattr(core_queue.TaskQueue, "schedule", fake_schedule)

    async def floody(ctx, *args, **kwargs):
        raise FloodWaitError(15)

    name = TaskName.WARMING_TICK.value
    wrapped = task(name)(floody)

    before = datetime.now(timezone.utc)
    result = await wrapped({"redis": None}, 42, account_id=7)
    after = datetime.now(timezone.utc)

    # не считается провалом — исключение не пробрасывается
    assert result is None
    assert len(spy) == 1
    call = spy[0]
    assert call["name"] == name
    assert call["args"] == (42,)
    assert call["kwargs"] == {"account_id": 7}
    # run_at ~ now + 15s
    delta_lo = (call["run_at"] - before).total_seconds()
    delta_hi = (call["run_at"] - after).total_seconds()
    assert 14.0 <= delta_lo <= 16.0
    assert 14.0 <= delta_hi <= 16.0


# --------------------------------------------------------------------------- #
# 5. Реальный arq-воркер забирает warming.initial_start из очереди и планирует
#    стартовую пачку warming.tick (замыкание пайплайна из _finish_login, #1/#2).
# --------------------------------------------------------------------------- #
class _LowRng:
    """rng, при котором randint возвращает нижнюю границу (детерминизм пачки)."""

    def randint(self, a, b):
        return a


class _SpyTaskQueue:
    def __init__(self):
        self.enqueued: list[tuple] = []

    async def enqueue(self, task_name, *args, **kwargs):
        self.enqueued.append((task_name, args))
        return "job-1"


@pytest.mark.asyncio
async def test_worker_runs_initial_start_and_schedules_ticks(arq_pool):
    spy = _SpyTaskQueue()

    async def startup(ctx):
        # initial_start сам ничего не пишет в БД: нужны только rng и task_queue.
        ctx["rng"] = _LowRng()
        ctx["task_queue"] = spy

    wrapped = func(
        warming_initial_start,
        name=TaskName.WARMING_INITIAL_START.value,
        max_tries=3,
    )

    tq = TaskQueue(redis=arq_pool)
    await tq.enqueue(TaskName.WARMING_INITIAL_START, 42)

    worker = Worker(
        functions=[wrapped],
        redis_pool=arq_pool,
        queue_name="default",
        on_startup=startup,
        burst=True,
        poll_delay=0.05,
        handle_signals=False,
    )
    await asyncio.wait_for(worker.async_run(), timeout=15)

    # Воркер реально забрал задачу и запланировал стартовую пачку warming.tick.
    # MEDIUM-профиль: randint(2, 5) → 2 при _LowRng.
    ticks = [args for name, args in spy.enqueued if name == TaskName.WARMING_TICK]
    assert len(ticks) == 2
    assert all(args == (42,) for args in ticks)
