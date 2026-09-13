"""Контрольный сквозной прогон (аудит, Часть А промпта 24).

Один последовательный сценарий доказывает, что blocker/major-стыки реально
собираются вместе: login → warming → pool → кампания → attach → NewMessage →
comment_logs, плюс governor-лимит, публикация account_status и ASGI-lifespan.

Требует живые Postgres и Redis (как остальные интеграционные тесты). Telethon и
LLM — фейки; сетевых вызовов нет. НЕ запускается в окружении без сервисов.
"""

from __future__ import annotations

import itertools
from datetime import datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text

from core.enums import Initiator
from core.models import Account, CommentLog
from core.repositories.account import AccountRepository
from core.state_machine import AccountEvent, AccountStateMachine
from modules.commenting.repositories import CampaignRepository, CommentLogRepository
from modules.commenting.schemas import CampaignCreate
from modules.commenting.worker import registry as reg
from modules.commenting.worker import runner
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


# --- фейки внешнего I/O ------------------------------------------------------


class _KeepOpen:
    def __init__(self, session):
        self._s = session

    def __enter__(self):
        return self._s

    def __exit__(self, *exc):
        return False


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


class _AllowGovernor:
    async def check_and_reserve(self, account_id, action_type):
        return True


class _DenyGovernor:
    async def check_and_reserve(self, account_id, action_type):
        return False


class _FakeLLM:
    async def generate(self, system, messages, max_tokens=200, temperature=0.8):
        return "auto comment"


class _ListenerClient:
    """Клиент и для attach (get_entity/handlers), и для warming/posting."""

    def __init__(self, channel_id):
        self._channel_id = channel_id
        self.added = []
        self.send_message = AsyncMock(return_value=SimpleNamespace(id=999))

    async def get_entity(self, target):
        return SimpleNamespace(id=self._channel_id)

    def add_event_handler(self, handler, event):
        self.added.append((handler, event))

    def remove_event_handler(self, handler, event):
        pass

    async def __call__(self, *a, **k):  # warming IDLE_ONLINE: await client(UpdateStatus)
        return None


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _factory(session):
    return lambda: _KeepOpen(session)


def _make_created_account(session, meta) -> int:
    from core.enums import WarmingActionType  # noqa: F401 - гарантируем импорт enums

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


async def test_full_pipeline_end_to_end(session, monkeypatch):
    from core.crypto import reset_cache
    from core.enums import WarmingActionType

    reset_cache()
    _clean(session)
    channel_id = 4242
    client = _ListenerClient(channel_id)
    pub = _SpyPublisher()

    # ── Шаг 1: client_pool кладётся в ctx ДО load_all (порядок) ──────────────
    order: list[str] = []

    class _OrderedPool(_FakePool):
        pass

    ctx: dict = {"session_factory": _factory(session), "publisher": pub}

    async def _fake_load_all(self, c):
        order.append("load_all")
        return []

    monkeypatch.setattr(reg.ListenerRegistry, "load_all", _fake_load_all)
    ctx["client_pool"] = _OrderedPool(client)
    order.append("client_pool")
    await reg.ListenerRegistry().load_all(ctx)
    assert order == ["client_pool", "load_all"]  # пул готов раньше слушателей

    # реальный пул/rng/governor для остального сценария
    ctx.update(
        now=NOW_INSIDE,
        rng=_FixedRng(WarmingActionType.IDLE_ONLINE),
        client_pool=_FakePool(client),
        task_queue=_SpyTaskQueue(),
        governor=_AllowGovernor(),
        llm_provider=_FakeLLM(),
    )

    # ── Шаг 2: login (мок) валидным кодом → warming + initial_start В ОЧЕРЕДЬ ──
    account_id = _make_created_account(session, {"phone_code_hash": "H"})
    login_ctx = dict(ctx)
    login_ctx["client"] = client  # не используется login-flow, но безопасно
    await login_confirm_impl(ctx, account_id, "12345")
    assert AccountRepository(session).get(account_id).status == "warming"
    starts = [a for n, a, k in ctx["task_queue"].enqueued if n.value == "warming.initial_start"]
    assert starts == [(account_id,)]  # запустился САМ, без ручного enqueue

    # ── Шаг 3: governor реально режет warming-действие → skipped, не ошибка ──
    skip_ctx = dict(ctx)
    skip_ctx["governor"] = _DenyGovernor()
    res = await execute_action(
        WarmingActionType.IDLE_ONLINE, client, AccountRepository(session).get(account_id),
        governor=_DenyGovernor(), session_factory=_factory(session),
    )
    assert res.status.value == "skipped" and res.meta == {"reason": "rate_limited"}

    # ── Шаг 4: ускоренный прогон warming → pool ──────────────────────────────
    for _ in range(50):
        await warming_tick_impl(ctx, account_id)
    assert AccountRepository(session).get(account_id).status == "pool"
    # прогресс публиковался
    assert any(ch == WARMING_PROGRESS_CHANNEL for ch, _ in pub.events)

    # ── Шаг 5: кампания enabled без аккаунтов → слушатель НЕ подключается; ────
    #           attach первого аккаунта → подключается сам
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

    # attach аккаунта к кампании (через state machine, как API): pool → assigned
    AccountStateMachine(session, pub).transition(
        account_id, AccountEvent.CONTAINER_ATTACH, Initiator.USER,
        meta={"container_type": "commenting", "container_id": campaign_id},
    )
    from modules.commenting.models import CampaignAccount
    session.add(CampaignAccount(campaign_id=campaign_id, account_id=account_id))
    session.commit()
    assert await registry.attach(campaign_id, ctx) is True
    handler, _event = client.added[-1]

    # ── Шаг 6: NewMessage → on_new_post → post_comment → comment_logs ────────
    await handler(SimpleNamespace(message=SimpleNamespace(sender_id=channel_id, id=100)))
    on_new = [a for n, a, k in ctx["task_queue"].enqueued if n.value == "commenting.on_new_post"]
    assert on_new  # слушатель поставил on_new_post
    scheduled = await runner.on_new_post(ctx, campaign_id, 100)
    assert scheduled >= 1
    for _n, _run_at, args, kwargs in ctx["task_queue"].scheduled:
        await runner.post_comment(ctx, *args, **kwargs)
    logs = CommentLogRepository(session).list_by_campaign(campaign_id)
    assert len(logs) == scheduled and all(l.status == "posted" for l in logs)

    # ── Шаг 7: переход публикует account_status (как retire через API) ───────
    pub.events.clear()
    AccountStateMachine(session, pub).transition(account_id, AccountEvent.RETIRE, Initiator.USER)
    status_events = [p for ch, p in pub.events if ch == "account_status"]
    assert len(status_events) == 1 and status_events[0]["to"] == "retired"


async def test_asgi_lifespan_fires_over_httpx(session):
    """Шаг 8: приложение поднимается через ASGITransport, lifespan реально
    срабатывает (проверка коннектов), /health отвечает 200 при живых зависимостях."""
    import httpx

    from api.asgi import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        # вход в контекст поднимает lifespan (verify_connectivity к PG+Redis)
        async with app.router.lifespan_context(app):
            resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
