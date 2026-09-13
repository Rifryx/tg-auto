"""Контрольный сквозной прогон (аудит, Часть А промпта 24).

Доказывает, что blocker/major-стыки собираются вместе в реальных потоках:
старт воркера → login → warming → pool → кампания → attach → NewMessage →
comment_logs, плюс governor-лимит, публикация account_status и ASGI-lifespan.

Порядок шагов = порядок тестов в файле:
  1. worker.main.startup: client_pool кладётся ДО ListenerRegistry.load_all().
  2–6. login(мок)→warming(initial_start сам)→governor-skip→pool→кампания→
       attach→NewMessage→comment_logs (один последовательный тест).
  7. retire через API-роут реально публикует в Redis-канал account_status.
  8. API через httpx+ASGITransport: lifespan срабатывает, /health = 200.

Telethon/LLM — фейки, сетевых вызовов в Telegram нет. Шаги 2–6 требуют только
Postgres; шаги 7–8 требуют и Redis (как остальные интеграционные тесты). Шаг 1
внешних сервисов не требует.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from datetime import datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text

from core.config import get_settings
from core.crypto import reset_cache
from core.enums import Initiator, WarmingActionType
from core.models import Account
from core.queue.publisher import RedisPublisher
from core.repositories.account import AccountRepository
from core.state_machine import AccountEvent, AccountStateMachine
from modules.commenting.models import CampaignAccount
from modules.commenting.repositories import CampaignRepository, CommentLogRepository
from modules.commenting.schemas import CampaignCreate
from modules.commenting.worker import registry as reg
from modules.commenting.worker import runner
from worker.client_pool import ClientPool
from worker.login import login_confirm_impl
from worker.tasks.warming import WARMING_PROGRESS_CHANNEL, warming_tick_impl
from worker.warming.actions import execute_action

pytestmark = pytest.mark.asyncio

NOW_INSIDE = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
_PHONE = itertools.count(70_000_000_000)
_TABLES = (
    "accounts",
    "health_events",
    "account_status_history",
    "warming_activities",
    '"commenting".campaigns',
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    reset_cache()
    get_settings.cache_clear()
    yield
    reset_cache()
    get_settings.cache_clear()


# --- фейки внешнего I/O ------------------------------------------------------


class _AllClient:
    """Один фейковый TelegramClient на весь сценарий: login + warming + posting."""

    def __init__(self, channel_id: int):
        self._channel_id = channel_id
        self.added: list = []
        self.session = SimpleNamespace(save=lambda: "e2e-session-string")
        self.send_message = AsyncMock(return_value=SimpleNamespace(id=999))

    # login
    async def connect(self):
        return None

    async def send_code_request(self, phone):
        return SimpleNamespace(phone_code_hash="H")

    async def sign_in(self, **kwargs):
        return SimpleNamespace()

    # commenting listener
    async def get_entity(self, target):
        return SimpleNamespace(id=self._channel_id)

    def add_event_handler(self, handler, event):
        self.added.append((handler, event))

    def remove_event_handler(self, handler, event):
        self.added = [(h, e) for h, e in self.added if h is not handler]

    # warming IDLE_ONLINE: await client(UpdateStatusRequest(...))
    async def __call__(self, *args, **kwargs):
        return None


class _FakePool:
    def __init__(self, client):
        self._client = client
        self.gets = 0

    async def get(self, account_id):
        self.gets += 1
        return self._client

    async def release(self, account_id):
        pass


class _SpyTaskQueue:
    def __init__(self):
        self.enqueued = []
        self.scheduled = []

    async def enqueue(self, name, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
        return "job"

    async def schedule(self, name, run_at, *args, **kwargs):
        self.scheduled.append((name, run_at, args, kwargs))
        return "job"


class _SpyPublisher:
    def __init__(self):
        self.events = []

    def publish(self, channel, payload):
        self.events.append((channel, dict(payload)))


class _FixedRng:
    def __init__(self, action):
        self._action = action

    def choice(self, seq):
        return self._action

    def randint(self, a, b):
        return a

    def uniform(self, a, b):
        return a

    def sample(self, population, k):
        return list(population)[:k]

    def random(self):
        return 0.99

    def shuffle(self, seq):
        return None


class _AllowGovernor:
    async def check_and_reserve(self, account_id, action_type):
        return True


class _DenyGovernor:
    async def check_and_reserve(self, account_id, action_type):
        return False


class _FakeLLM:
    async def generate(self, system, messages, max_tokens=200, temperature=0.8):
        return "auto comment"


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


def _make_created_account(session, meta) -> int:
    acc = Account(
        phone=f"+{next(_PHONE)}",
        session_enc=b"enc",
        status="created",
        meta=meta,
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    session.add(acc)
    session.flush()
    session.commit()
    return acc.id


# ── Шаг 1: startup — client_pool готов ДО load_all (внешних сервисов не нужно) ─


async def test_step1_client_pool_ready_before_load_all(monkeypatch):
    import worker.main as wm

    seen: dict = {}

    async def spy_load_all(self, ctx):
        seen["pool_ready"] = ctx.get("client_pool") is not None
        return []

    async def noop_run(self):  # не поднимаем реальную подписку на Redis
        return None

    monkeypatch.setattr(reg.ListenerRegistry, "load_all", spy_load_all)
    monkeypatch.setattr(reg.CampaignLifecycleListener, "run", noop_run)

    ctx: dict = {"redis": object()}
    await wm.startup(ctx)
    task = ctx.get("campaign_lifecycle_task")
    if task is not None:
        task.cancel()

    assert seen.get("pool_ready") is True  # порядок: пул раньше слушателей
    assert isinstance(ctx["client_pool"], ClientPool)


# ── Шаги 2–6: login → warming → pool → кампания → attach → comment_logs ───────


async def test_steps2_6_login_to_comment_logs(session):
    channel_id = 4242
    client = _AllClient(channel_id)
    pub = _SpyPublisher()
    _clean(session)

    ctx = {
        "session_factory": _factory(session),
        "publisher": pub,
        "now": NOW_INSIDE,
        "rng": _FixedRng(WarmingActionType.IDLE_ONLINE),
        "client_pool": _FakePool(client),
        "task_queue": _SpyTaskQueue(),
        "governor": _AllowGovernor(),
        "llm_provider": _FakeLLM(),
    }

    # Шаг 2: login валидным кодом (мок) → warming; initial_start встаёт САМ
    account_id = _make_created_account(session, {"phone_code_hash": "H"})
    await login_confirm_impl(ctx, account_id, "12345")
    assert AccountRepository(session).get(account_id).status == "warming"
    starts = [
        a for n, a, _k in ctx["task_queue"].enqueued
        if getattr(n, "value", n) == "warming.initial_start"
    ]
    assert starts == [(account_id,)]  # без ручного enqueue в тесте

    # Шаг 3: governor исчерпан → действие skipped, не ошибка
    res = await execute_action(
        WarmingActionType.IDLE_ONLINE,
        client,
        AccountRepository(session).get(account_id),
        governor=_DenyGovernor(),
        session_factory=_factory(session),
    )
    assert res.status.value == "skipped"
    assert res.meta == {"reason": "rate_limited"}

    # Шаг 4: ускоренный прогон warming → pool
    for _ in range(50):
        await warming_tick_impl(ctx, account_id)
    assert AccountRepository(session).get(account_id).status == "pool"
    assert any(ch == WARMING_PROGRESS_CHANNEL for ch, _ in pub.events)  # #9 прогресс

    # Шаг 5: enabled-кампания без аккаунтов → слушатель НЕ подключается;
    #        attach первого аккаунта → подключается сам, без рестарта
    campaign_id = CampaignRepository(session).create(
        CampaignCreate(
            name="c", target_channel="@ch", base_system_prompt="p", llm_provider="deepseek",
            active_hours_start=time(0, 0), active_hours_end=time(23, 59), active_hours_tz="UTC",
            posting_delay_min_sec=1, posting_delay_max_sec=2, discussion_group_id=555,
        )
    ).id
    session.commit()

    registry = reg.ListenerRegistry()
    assert await registry.attach(campaign_id, ctx) is False  # нет assigned-аккаунтов

    AccountStateMachine(session, pub).transition(
        account_id, AccountEvent.CONTAINER_ATTACH, Initiator.USER,
        meta={"container_type": "commenting", "container_id": campaign_id},
    )
    session.add(CampaignAccount(campaign_id=campaign_id, account_id=account_id))
    session.commit()
    assert await registry.attach(campaign_id, ctx) is True
    handler, _event = client.added[-1]

    # Шаг 6: NewMessage самого канала → on_new_post → post_comment → comment_logs
    await handler(SimpleNamespace(message=SimpleNamespace(sender_id=channel_id, id=100)))
    on_new = [
        a for n, a, _k in ctx["task_queue"].enqueued
        if getattr(n, "value", n) == "commenting.on_new_post"
    ]
    assert on_new  # слушатель поставил on_new_post

    scheduled = await runner.on_new_post(ctx, campaign_id, 100)
    assert scheduled >= 1
    for _n, _run_at, args, kwargs in list(ctx["task_queue"].scheduled):
        await runner.post_comment(ctx, *args, **kwargs)
    logs = CommentLogRepository(session).list_by_campaign(campaign_id)
    assert len(logs) == scheduled
    assert all(log.status == "posted" for log in logs)


# ── Шаг 7: retire через API-роут реально публикует в Redis account_status ─────


async def test_step7_api_retire_publishes_account_status(session):
    import httpx
    import redis as sync_redis
    import redis.asyncio as aioredis
    from fastapi import FastAPI

    from api.deps.auth import require_user
    from api.deps.db import get_session
    from api.deps.queue import get_publisher
    from api.routers import accounts as accounts_router

    _clean(session)
    account_id = _make_created_account(session, {})  # 'created' → RETIRE допустим
    redis_url = get_settings().redis_url

    app = FastAPI()
    app.include_router(accounts_router.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: "tester"
    app.dependency_overrides[get_publisher] = lambda: RedisPublisher(
        sync_redis.Redis.from_url(redis_url)
    )

    sub = aioredis.from_url(redis_url)
    pubsub = sub.pubsub()
    await pubsub.subscribe("account_status")
    try:
        await asyncio.sleep(0.1)  # дренаж подтверждения подписки
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.post(f"/accounts/{account_id}/actions/retire")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "retired"

        payload = None
        for _ in range(200):
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
            if msg and msg.get("type") == "message":
                payload = json.loads(msg["data"])
                break
            await asyncio.sleep(0.02)
        assert payload is not None, "account_status не пришёл в Redis"
        assert payload["account_id"] == account_id
        assert payload["to"] == "retired"
        assert payload["initiator"] == "user"
    finally:
        await pubsub.aclose()
        await sub.aclose()


# ── Шаг 8: ASGI-lifespan через httpx.ASGITransport, /health = 200 ─────────────


async def test_step8_asgi_lifespan_and_health():
    import httpx

    from api.asgi import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        async with app.router.lifespan_context(app):  # lifespan → verify_connectivity
            resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
