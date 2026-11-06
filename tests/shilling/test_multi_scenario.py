"""Несколько сценариев на кампанию: список, создание, активация, удаление.

БД настоящая (CI/postgres). Проверяем, что у кампании может быть много
сценариев, активный переключается, рассылка (get_by_campaign) смотрит именно
на активный, а удаление активного переназначает его на оставшийся.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from modules.shilling.api import router as shilling_router
from modules.shilling.repositories import CampaignRepository, ScenarioRepository

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


def _campaign(api) -> int:
    return api.post(
        "/modules/shilling/campaigns", json={"name": "c", "brand_name": "B"}
    ).json()["id"]


def _scenarios(api, cid):
    return api.get(f"/modules/shilling/campaigns/{cid}/scenarios").json()


async def test_first_scenario_is_active_rest_are_not(session, monkeypatch):
    monkeypatch.delenv("BILLING_BYPASS_LIMITS", raising=False)
    api = _client(session)
    cid = _campaign(api)

    s1 = api.post(
        f"/modules/shilling/campaigns/{cid}/scenarios",
        json={"name": "Сценарий 1", "persons_count": 2},
    )
    assert s1.status_code == 201
    s2 = api.post(
        f"/modules/shilling/campaigns/{cid}/scenarios",
        json={"name": "Сценарий 2", "persons_count": 3},
    )
    assert s2.status_code == 201

    items = _scenarios(api, cid)
    assert len(items) == 2
    by_name = {i["name"]: i for i in items}
    # Первый сразу активный, второй — нет (случайный «Новый» не переключает).
    assert by_name["Сценарий 1"]["is_active"] is True
    assert by_name["Сценарий 2"]["is_active"] is False


async def test_activate_switches_active_and_drives_dispatch(session, monkeypatch):
    monkeypatch.delenv("BILLING_BYPASS_LIMITS", raising=False)
    api = _client(session)
    cid = _campaign(api)
    s1 = api.post(f"/modules/shilling/campaigns/{cid}/scenarios", json={"persons_count": 2}).json()
    s2 = api.post(f"/modules/shilling/campaigns/{cid}/scenarios", json={"persons_count": 2}).json()

    r = api.post(f"/modules/shilling/campaigns/{cid}/scenarios/{s2['id']}/activate")
    assert r.status_code == 200

    # campaigns.scenario_id указывает на s2, и рассылка смотрит на него же.
    assert CampaignRepository(session).get(cid).scenario_id == s2["id"]
    active = ScenarioRepository(session).get_by_campaign(cid)
    assert active.id == s2["id"]

    items = {i["id"]: i["is_active"] for i in _scenarios(api, cid)}
    assert items[s2["id"]] is True
    assert items[s1["id"]] is False


async def test_activate_foreign_scenario_404(session, monkeypatch):
    monkeypatch.delenv("BILLING_BYPASS_LIMITS", raising=False)
    api = _client(session)
    cid = _campaign(api)
    api.post(f"/modules/shilling/campaigns/{cid}/scenarios", json={"persons_count": 2})
    r = api.post(f"/modules/shilling/campaigns/{cid}/scenarios/999999/activate")
    assert r.status_code == 404


async def test_delete_active_reassigns_to_remaining(session, monkeypatch):
    monkeypatch.delenv("BILLING_BYPASS_LIMITS", raising=False)
    api = _client(session)
    cid = _campaign(api)
    s1 = api.post(f"/modules/shilling/campaigns/{cid}/scenarios", json={"persons_count": 2}).json()
    s2 = api.post(f"/modules/shilling/campaigns/{cid}/scenarios", json={"persons_count": 2}).json()
    # s1 активен. Удаляем его — активным должен стать s2.
    r = api.delete(f"/modules/shilling/campaigns/{cid}/scenarios/{s1['id']}")
    assert r.status_code == 204
    assert CampaignRepository(session).get(cid).scenario_id == s2["id"]
    items = _scenarios(api, cid)
    assert [i["id"] for i in items] == [s2["id"]]
    assert items[0]["is_active"] is True


async def test_delete_last_scenario_leaves_campaign_without_active(session, monkeypatch):
    monkeypatch.delenv("BILLING_BYPASS_LIMITS", raising=False)
    api = _client(session)
    cid = _campaign(api)
    s1 = api.post(f"/modules/shilling/campaigns/{cid}/scenarios", json={"persons_count": 2}).json()
    r = api.delete(f"/modules/shilling/campaigns/{cid}/scenarios/{s1['id']}")
    assert r.status_code == 204
    assert CampaignRepository(session).get(cid).scenario_id is None
    assert _scenarios(api, cid) == []


async def test_scenarios_list_reports_counts(session, monkeypatch):
    monkeypatch.delenv("BILLING_BYPASS_LIMITS", raising=False)
    api = _client(session)
    cid = _campaign(api)
    sid = api.post(f"/modules/shilling/campaigns/{cid}/scenarios", json={"persons_count": 2}).json()["id"]
    role = api.post(f"/modules/shilling/scenarios/{sid}/roles", json={"name": "Инициатор"}).json()
    api.post(
        f"/modules/shilling/scenarios/{sid}/steps",
        json={"role_id": role["id"], "step_type": "message", "text": "привет"},
    )
    item = _scenarios(api, cid)[0]
    assert item["roles_count"] == 1
    assert item["steps_count"] == 1
