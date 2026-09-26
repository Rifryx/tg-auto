"""Тесты лимитов плана для модуля shilling (402 при превышении).

БД настоящая (CI/postgres). План — free (по умолчанию). BILLING_BYPASS_LIMITS
не должен быть выставлен.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from modules.shilling.api import router as shilling_router

pytestmark = pytest.mark.asyncio


class _SpyTaskQueue:
    async def enqueue(self, *a, **k):
        return "job"

    async def schedule(self, *a, **k):
        return "job"


def _client(session):
    app = FastAPI()
    app.include_router(shilling_router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: "tester"
    app.dependency_overrides[get_task_queue] = lambda: _SpyTaskQueue()
    return TestClient(app)


def _scenario(api, cid):
    return api.put(f"/modules/shilling/campaigns/{cid}/scenario", json={"persons_count": 2}).json()["id"]


async def test_campaigns_limit_free_plan(session, monkeypatch):
    monkeypatch.delenv("BILLING_BYPASS_LIMITS", raising=False)
    api = _client(session)
    # free: 1 кампания
    r1 = api.post("/modules/shilling/campaigns", json={"name": "a", "brand_name": "B"})
    assert r1.status_code == 201
    r2 = api.post("/modules/shilling/campaigns", json={"name": "b", "brand_name": "B"})
    assert r2.status_code == 402
    assert r2.json()["detail"]["feature"] == "shilling_campaigns_active_max"


async def test_targets_limit_free_plan(session, monkeypatch):
    monkeypatch.delenv("BILLING_BYPASS_LIMITS", raising=False)
    api = _client(session)
    cid = api.post("/modules/shilling/campaigns", json={"name": "t", "brand_name": "B"}).json()["id"]
    # free: 10 целей — добавим 10, 11-я партия должна упереться
    raws = [f"@chan_{i}" for i in range(10)]
    r = api.post(f"/modules/shilling/campaigns/{cid}/targets", json={"raw_inputs": raws})
    assert r.status_code == 201 and len(r.json()) == 10
    r2 = api.post(f"/modules/shilling/campaigns/{cid}/targets", json={"raw_inputs": ["@more"]})
    assert r2.status_code == 402
    assert r2.json()["detail"]["feature"] == "shilling_targets_per_campaign_max"


async def test_steps_limit_free_plan(session, monkeypatch):
    monkeypatch.delenv("BILLING_BYPASS_LIMITS", raising=False)
    api = _client(session)
    cid = api.post("/modules/shilling/campaigns", json={"name": "s", "brand_name": "B"}).json()["id"]
    sid = _scenario(api, cid)
    role = api.post(f"/modules/shilling/scenarios/{sid}/roles", json={"name": "R"}).json()["id"]
    # free: 6 шагов
    for i in range(6):
        rr = api.post(
            f"/modules/shilling/scenarios/{sid}/steps",
            json={"role_id": role, "step_type": "message", "text": f"t{i}"},
        )
        assert rr.status_code == 201
    r7 = api.post(
        f"/modules/shilling/scenarios/{sid}/steps",
        json={"role_id": role, "step_type": "message", "text": "over"},
    )
    assert r7.status_code == 402
    assert r7.json()["detail"]["feature"] == "shilling_scenario_steps_max"
