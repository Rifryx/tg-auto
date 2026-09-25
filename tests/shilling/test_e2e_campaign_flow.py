"""E2E: создание кампании через API → прогон воркера → проверка логов/статы.

БД настоящая (CI/postgres). API — через TestClient (auth/queue замоканы).
Воркер запускается вручную с фейками Telethon/LLM/governor.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from core.models import Account
from core.queue.task_names import TaskName
from modules.shilling.api import router as shilling_router
from modules.shilling.repositories import ExecutionLogRepository
from modules.shilling.worker import executor, orchestrator

pytestmark = pytest.mark.asyncio

_PHONE = itertools.count(90_500_000_000)


class _SpyTaskQueue:
    def __init__(self):
        self.enqueued = []
        self.scheduled = []

    async def enqueue(self, name, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
        return "job"

    async def schedule(self, name, run_at, *args, **kwargs):
        self.scheduled.append((name, args, kwargs))
        return "job"


class _FakeClient:
    """И резолв канала, и отправка сообщений."""

    def __init__(self):
        self.sent = []
        self._id = itertools.count(1000)

    async def get_entity(self, ref):
        return SimpleNamespace(id=-100, title="Channel", username="chan")

    async def get_messages(self, entity, limit=1):
        return [SimpleNamespace(id=42)]

    async def __call__(self, request):
        n = type(request).__name__
        if "GetFullChannel" in n:
            return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=-200))
        if "GetDiscussionMessage" in n:
            return SimpleNamespace(messages=[SimpleNamespace(id=777)])
        return None

    async def send_message(self, chat_id, text, reply_to=None):
        self.sent.append((chat_id, text, reply_to))
        return SimpleNamespace(id=next(self._id))


class _FakePool:
    def __init__(self, client):
        self._client = client

    async def get(self, account_id):
        return self._client

    async def release(self, account_id):
        pass


class _FakeGovernor:
    async def check_and_reserve(self, account_id, action_type):
        return True


class _FakeLLM:
    async def generate(self, system, messages, max_tokens=200, temperature=0.8):
        return "текст"


class _Rng:
    def uniform(self, a, b):
        return 0

    def choice(self, seq):
        return seq[0]


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


def _client(session, spy):
    app = FastAPI()
    app.include_router(shilling_router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: "tester"
    app.dependency_overrides[get_task_queue] = lambda: spy
    return TestClient(app)


def _pool_account(session) -> int:
    acc = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="pool",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(acc)
    session.flush()
    session.commit()
    return acc.id


async def test_e2e_campaign_flow(session):
    spy = _SpyTaskQueue()
    api = _client(session, spy)

    # 1) Кампания
    r = api.post("/modules/shilling/campaigns", json={"name": "E2E", "brand_name": "Beauty Zone"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]

    # 2) Сценарий
    r = api.put(f"/modules/shilling/campaigns/{cid}/scenario", json={"persons_count": 2})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    # 3) Роли (2)
    r1 = api.post(f"/modules/shilling/scenarios/{sid}/roles", json={"name": "Инициатор"})
    r2 = api.post(f"/modules/shilling/scenarios/{sid}/roles", json={"name": "Ответчик"})
    role1, role2 = r1.json()["id"], r2.json()["id"]

    # 4) Шаги (3): вопрос → ответ → ответ
    for role_id, text in [(role1, "вопрос?"), (role2, "ответ про Beauty Zone"), (role2, "ещё раз Beauty Zone")]:
        rs = api.post(
            f"/modules/shilling/scenarios/{sid}/steps",
            json={"role_id": role_id, "step_type": "message", "text": text},
        )
        assert rs.status_code == 201, rs.text

    # 5) Аккаунты (2) на роли
    a1, a2 = _pool_account(session), _pool_account(session)
    assert api.post(f"/modules/shilling/campaigns/{cid}/accounts", json={"account_id": a1, "role_id": role1}).status_code == 201
    assert api.post(f"/modules/shilling/campaigns/{cid}/accounts", json={"account_id": a2, "role_id": role2}).status_code == 201

    # 6) Цель
    r = api.post(f"/modules/shilling/campaigns/{cid}/targets", json={"raw_inputs": ["@beauty_chat"]})
    assert r.status_code == 201, r.text
    target_id = r.json()[0]["id"]

    # 7) Готовность
    rd = api.get(f"/modules/shilling/campaigns/{cid}/readiness").json()
    assert rd["accounts"]["ok"] and rd["scenario"]["ok"] and rd["targets"]["ok"]
    assert rd["can_run"] is True

    # 8) Старт
    r = api.post(f"/modules/shilling/campaigns/{cid}/start")
    assert r.status_code == 200 and r.json()["status"] == "running"
    assert any(n == TaskName.SHILLING_START_CAMPAIGN for n, _, _ in spy.enqueued)

    # 9) Прогон воркера вручную (фейки).
    client = _FakeClient()
    ctx = {
        "session_factory": _factory(session),
        "now": None,
        "rng": _Rng(),
        "task_queue": spy,
        "client_pool": _FakePool(client),
        "governor": _FakeGovernor(),
        "llm_provider": _FakeLLM(),
        "publisher": None,
    }

    spy.scheduled.clear()
    n_targets = await orchestrator.start_campaign(ctx, cid)
    assert n_targets == 1
    # start_campaign → process_target
    proc = [s for s in spy.scheduled if s[0] == TaskName.SHILLING_PROCESS_TARGET]
    assert len(proc) == 1

    spy.scheduled.clear()
    n_steps = await orchestrator.process_target(ctx, cid, target_id)
    assert n_steps == 3
    steps = [s for s in spy.scheduled if s[0] == TaskName.SHILLING_EXECUTE_STEP]
    assert len(steps) == 3

    # execute_step для каждого запланированного шага
    for _name, args, kwargs in steps:
        await executor.execute_step(ctx, *args, **kwargs)

    # 10) Логи: 3 sent
    logs = ExecutionLogRepository(session).list_by_campaign(cid)
    assert len(logs) == 3
    assert all(l.status == "sent" for l in logs)
    assert len(client.sent) == 3

    # 11) Статистика
    st = api.get(f"/modules/shilling/campaigns/{cid}/stats").json()
    assert st["total"] == 3 and st["sent"] == 3 and st["success_rate_percent"] == 100
