"""E2E-тесты оркестрации логина (PROJECT-STAGES §11).

Проверяют связку API ↔ Redis pub/sub без реального воркера/Telethon: команды
уходят в spy-очередь, «воркер» имитируется публикацией событий в Redis-канал
``login``, а SSE-эндпоинт доставляет их клиенту.

SSE-стрим бесконечный, поэтому HTTP-транспорт httpx (ASGITransport буферизует
ответ целиком) для него не годится — стрим проверяется прямым итерированием
``StreamingResponse.body_iterator`` эндпоинта в одном event loop. Обычные (не-
стриминговые) ручки POST/GET дёргаются через httpx.AsyncClient.

Требуется живой Redis (docker: neuro_redis на 6379).
"""

from __future__ import annotations

import asyncio
import os
import itertools
import json

import httpx
import pytest
import redis.asyncio as aioredis
from fastapi import FastAPI

import redis as sync_redis

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_publisher, get_task_queue
from api.routers import accounts as accounts_router
from api.routers import login as login_router
from api.services.login import LoginEventHub, get_login_hub
from core.queue.publisher import RedisPublisher
from core.enums import Initiator
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from core.schemas.account import AccountCreate
from core.state_machine import AccountEvent, AccountStateMachine

pytestmark = pytest.mark.asyncio

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")
_PHONE = itertools.count(60_000_000_000)


class _SpyTaskQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple] = []

    async def enqueue(self, task_name, *args, **kwargs):
        self.enqueued.append((task_name, args, kwargs))
        return "job-1"


class _FakeRequest:
    """Минимальный Request для прямого вызова SSE-эндпоинта (клиент не отпал)."""

    async def is_disconnected(self) -> bool:
        return False


def _make_account(session) -> int:
    account = AccountRepository(session).create(
        AccountCreate(
            phone=f"+{next(_PHONE)}",
            session_enc=b"enc",
            device_model="iPhone15,3",
            system_version="17.5.1",
            app_version="10.14.5",
            lang_code="uk",
            system_lang_code="uk-UA",
        )
    )
    session.commit()
    return account.id


@pytest.fixture
def hub():
    return LoginEventHub(REDIS_URL)


@pytest.fixture
def spy():
    return _SpyTaskQueue()


@pytest.fixture
def app(session, hub, spy):
    application = FastAPI()
    application.include_router(login_router.router)
    application.dependency_overrides[get_session] = lambda: session
    application.dependency_overrides[get_task_queue] = lambda: spy
    application.dependency_overrides[get_login_hub] = lambda: hub
    application.dependency_overrides[require_user] = lambda: "test-user"
    return application


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _open_stream(account_id, session, hub):
    """Возвращает body_iterator SSE после маркера ': connected'."""
    resp = await login_router.login_stream(
        account_id, request=_FakeRequest(), session=session, hub=hub
    )
    agen = resp.body_iterator
    first = await asyncio.wait_for(agen.__anext__(), timeout=5)
    assert "connected" in first
    return agen


async def _publish_until_delivered(
    pub, payload: dict, tries: int = 200, channel: str = "login"
) -> None:
    data = json.dumps(payload)
    for _ in range(tries):
        if await pub.publish(channel, data) >= 1:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"no subscriber received the {channel} event")


async def _read_data(agen, max_chunks: int = 20) -> dict:
    for _ in range(max_chunks):
        chunk = await asyncio.wait_for(agen.__anext__(), timeout=5)
        if chunk.startswith("data:"):
            return json.loads(chunk[len("data:") :].strip())
    raise AssertionError("no SSE data event received")


# --- 1. start кладёт задачу; событие waiting_code доходит до SSE --------------


async def test_start_enqueues_and_sse_receives_waiting_code(app, session, hub, spy):
    account_id = _make_account(session)
    pub = aioredis.from_url(REDIS_URL)
    try:
        async with _client(app) as client:
            resp = await client.post(f"/accounts/{account_id}/login/start")
            assert resp.status_code == 200
            assert spy.enqueued == [(TaskName.ACCOUNT_LOGIN_START, (account_id,), {})]

        agen = await _open_stream(account_id, session, hub)
        try:
            await _publish_until_delivered(
                pub, {"account_id": account_id, "state": "waiting_code"}
            )
            event = await _read_data(agen)
            assert event["account_id"] == account_id
            assert event["state"] == "waiting_code"
        finally:
            await agen.aclose()
    finally:
        await hub.stop()
        await pub.aclose()


# --- 2. SSE держит соединение и получает второе событие ----------------------


async def test_sse_receives_second_event(app, session, hub):
    account_id = _make_account(session)
    pub = aioredis.from_url(REDIS_URL)
    try:
        agen = await _open_stream(account_id, session, hub)
        try:
            await _publish_until_delivered(
                pub, {"account_id": account_id, "state": "waiting_code"}
            )
            assert (await _read_data(agen))["state"] == "waiting_code"

            await _publish_until_delivered(
                pub, {"account_id": account_id, "state": "waiting_password"}
            )
            assert (await _read_data(agen))["state"] == "waiting_password"
        finally:
            await agen.aclose()
    finally:
        await hub.stop()
        await pub.aclose()


# --- 3. GET /login/state после успеха отдаёт success + timestamp -------------


async def test_state_after_success(app, session, hub):
    account_id = _make_account(session)
    pub = aioredis.from_url(REDIS_URL)
    try:
        agen = await _open_stream(account_id, session, hub)
        try:
            await _publish_until_delivered(
                pub, {"account_id": account_id, "state": "success"}
            )
            # дождались доставки — значит хаб закэшировал состояние
            assert (await _read_data(agen))["state"] == "success"
        finally:
            await agen.aclose()

        async with _client(app) as client:
            resp = await client.get(f"/accounts/{account_id}/login/state")
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "success"
        assert body["updated_at"] is not None
    finally:
        await hub.stop()
        await pub.aclose()


# --- 3a. retire ЧЕРЕЗ API-роут реально публикует в account_status (#9) --------


async def test_api_retire_publishes_account_status_to_redis(session):
    """POST /accounts/{id}/actions/retire (через API, не воркер) → событие
    реально приходит в Redis-канал account_status (подписка напрямую)."""
    account_id = _make_account(session)

    app = FastAPI()
    app.include_router(accounts_router.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: "tester"
    # реальный публикатор на синхронном redis-клиенте к тому же Redis
    publisher = RedisPublisher(sync_redis.Redis.from_url(REDIS_URL))
    app.dependency_overrides[get_publisher] = lambda: publisher

    sub = aioredis.from_url(REDIS_URL)
    pubsub = sub.pubsub()
    await pubsub.subscribe("account_status")
    try:
        # дренаж подтверждения подписки
        await asyncio.sleep(0.1)
        async with _client(app) as client:
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


# --- 3b. переход публикует account_status РОВНО один раз (#9, без дублей) -----


async def test_transition_publishes_account_status_once(session):
    """State machine публикует account_status один раз на переход — независимо
    от инициатора (API или воркер). API не добавляет вторую публикацию сверху."""
    events: list[tuple[str, dict]] = []

    class _Spy:
        def publish(self, channel, payload):
            events.append((channel, dict(payload)))

    account_id = _make_account(session)
    # RETIRE из created (как это сделал бы API-роут /actions/retire с реальным
    # publisher из get_publisher()).
    AccountStateMachine(session, _Spy()).transition(
        account_id, AccountEvent.RETIRE, Initiator.USER
    )

    status_events = [p for ch, p in events if ch == "account_status"]
    assert len(status_events) == 1  # ровно одно событие, без дублей
    assert status_events[0]["account_id"] == account_id
    assert status_events[0]["to"] == "retired"


# --- 4. account_status доходит до SSE (универсальный стрим, #9) ---------------


async def test_sse_receives_account_status_event(app, session, hub):
    """Тот же per-account SSE отдаёт события канала account_status (не только login)."""
    account_id = _make_account(session)
    pub = aioredis.from_url(REDIS_URL)
    try:
        agen = await _open_stream(account_id, session, hub)
        try:
            await _publish_until_delivered(
                pub,
                {
                    "account_id": account_id,
                    "from": "pool",
                    "to": "cooldown",
                    "reason": "health.incident",
                    "initiator": "health",
                },
                channel="account_status",
            )
            event = await _read_data(agen)
            assert event["type"] == "account_status"
            assert event["to"] == "cooldown"
            assert event["from"] == "pool"
        finally:
            await agen.aclose()
    finally:
        await hub.stop()
        await pub.aclose()
