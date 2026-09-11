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
import itertools
import json

import httpx
import pytest
import redis.asyncio as aioredis
from fastapi import FastAPI

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from api.routers import login as login_router
from api.services.login import LoginEventHub, get_login_hub
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from core.schemas.account import AccountCreate

pytestmark = pytest.mark.asyncio

REDIS_URL = "redis://localhost:6379/1"
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


async def _publish_until_delivered(pub, payload: dict, tries: int = 200) -> None:
    data = json.dumps(payload)
    for _ in range(tries):
        if await pub.publish("login", data) >= 1:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("no subscriber received the login event")


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
