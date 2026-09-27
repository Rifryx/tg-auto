"""Промпт 2.4: REST-эндпоинты кампаний прайминга.

E2E-тесты через TestClient + fake TaskQueue. Требуют postgres_test.
"""

from __future__ import annotations

import itertools

import pytest

pytest.importorskip("telethon")
pytest.importorskip("structlog")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from core.models import Account
from core.queue.task_names import TaskName
from modules.priming.api.router import router as priming_router
from modules.priming.repositories import (
    CampaignAccountRepository,
    CampaignTargetRepository,
)


_PHONE = itertools.count(96_000_000_000)


class _SpyTaskQueue:
    def __init__(self):
        self.enqueued = []
    async def enqueue(self, name, *args, **kwargs):
        self.enqueued.append((name, args))
        return "job"
    async def schedule(self, name, run_at, *args, **kwargs):
        self.enqueued.append((name, args))
        return "job"


def _client(session, spy):
    app = FastAPI()
    app.include_router(priming_router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: "1"  # int-совместимый user_id
    app.dependency_overrides[get_task_queue] = lambda: spy
    return TestClient(app)


def _make_account(session) -> int:
    acc = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="pool",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(acc)
    session.flush()
    session.commit()
    return acc.id


def _minimal_body() -> dict:
    return {
        "name": "T",
        "trigger_action": "secret_chat_request",
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_create_and_get_campaign(session) -> None:
    api = _client(session, _SpyTaskQueue())
    r = api.post("/modules/priming/campaigns", json=_minimal_body())
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["status"] == "draft"
    assert r.json()["trigger_action"] == "secret_chat_request"
    assert r.json()["created_by"] == 1

    r = api.get(f"/modules/priming/campaigns/{cid}")
    assert r.status_code == 200
    assert r.json()["id"] == cid


def test_list_campaigns_sorted(session) -> None:
    api = _client(session, _SpyTaskQueue())
    ids = [
        api.post("/modules/priming/campaigns", json={**_minimal_body(), "name": f"c{i}"}).json()["id"]
        for i in range(3)
    ]
    r = api.get("/modules/priming/campaigns")
    assert r.status_code == 200
    assert [row["id"] for row in r.json()][:3] == list(reversed(ids))


def test_update_campaign_in_draft(session) -> None:
    api = _client(session, _SpyTaskQueue())
    cid = api.post("/modules/priming/campaigns", json=_minimal_body()).json()["id"]
    r = api.patch(
        f"/modules/priming/campaigns/{cid}", json={"name": "new", "daily_limit_per_account": 20},
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "new"
    assert r.json()["daily_limit_per_account"] == 20


def test_update_rejects_when_running(session) -> None:
    api = _client(session, _SpyTaskQueue())
    cid = api.post("/modules/priming/campaigns", json=_minimal_body()).json()["id"]
    # Прикрепить аккаунт и цель, чтобы кампания могла стартовать.
    _make_account(session)
    from core.models import Account
    account_id = session.query(Account).order_by(Account.id.desc()).first().id
    CampaignAccountRepository(session).create({"campaign_id": cid, "account_id": account_id})
    CampaignTargetRepository(session).create({"campaign_id": cid, "username": "u"})
    session.commit()

    assert api.post(f"/modules/priming/campaigns/{cid}/start").status_code == 200
    r = api.patch(f"/modules/priming/campaigns/{cid}", json={"name": "x"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "conflict"


def test_delete_only_terminal_statuses(session) -> None:
    api = _client(session, _SpyTaskQueue())
    cid = api.post("/modules/priming/campaigns", json=_minimal_body()).json()["id"]
    r = api.delete(f"/modules/priming/campaigns/{cid}")
    assert r.status_code == 204

    # Второй раз — 404.
    r = api.delete(f"/modules/priming/campaigns/{cid}")
    assert r.status_code == 404


def test_get_missing_campaign_returns_404(session) -> None:
    api = _client(session, _SpyTaskQueue())
    r = api.get("/modules/priming/campaigns/999999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_start_requires_accounts_and_targets(session) -> None:
    api = _client(session, _SpyTaskQueue())
    cid = api.post("/modules/priming/campaigns", json=_minimal_body()).json()["id"]

    # Нет аккаунтов и целей → 422.
    r = api.post(f"/modules/priming/campaigns/{cid}/start")
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "validation_error"

    # Только аккаунт — всё ещё 422 (нет целей).
    account_id = _make_account(session)
    CampaignAccountRepository(session).create({"campaign_id": cid, "account_id": account_id})
    session.commit()
    r = api.post(f"/modules/priming/campaigns/{cid}/start")
    assert r.status_code == 422

    # Плюс цель → 200 и запись в task_queue.
    CampaignTargetRepository(session).create({"campaign_id": cid, "username": "u"})
    session.commit()
    spy = _SpyTaskQueue()
    api = _client(session, spy)
    r = api.post(f"/modules/priming/campaigns/{cid}/start")
    assert r.status_code == 200
    assert r.json()["status"] == "running"
    assert r.json()["started_at"] is not None
    # В task_queue приземлился orchestrator_tick.
    assert any(
        name == TaskName.PRIMING_ORCHESTRATOR_TICK.value
        for name, _args in spy.enqueued
    )


def test_pause_resume_stop_transitions(session) -> None:
    api = _client(session, _SpyTaskQueue())
    cid = api.post("/modules/priming/campaigns", json=_minimal_body()).json()["id"]
    account_id = _make_account(session)
    CampaignAccountRepository(session).create({"campaign_id": cid, "account_id": account_id})
    CampaignTargetRepository(session).create({"campaign_id": cid, "username": "u"})
    session.commit()

    # start → running
    spy = _SpyTaskQueue()
    api = _client(session, spy)
    assert api.post(f"/modules/priming/campaigns/{cid}/start").json()["status"] == "running"

    # pause → paused
    r = api.post(f"/modules/priming/campaigns/{cid}/pause")
    assert r.status_code == 200
    assert r.json()["status"] == "paused"

    # pause с paused → 409
    r = api.post(f"/modules/priming/campaigns/{cid}/pause")
    assert r.status_code == 409

    # resume → running и второй orchestrator_tick в task_queue
    assert api.post(f"/modules/priming/campaigns/{cid}/resume").json()["status"] == "running"
    orchestrator_names = [
        name for name, _ in spy.enqueued
        if name == TaskName.PRIMING_ORCHESTRATOR_TICK.value
    ]
    assert len(orchestrator_names) >= 2  # start + resume

    # stop → stopped и finished_at выставлен
    r = api.post(f"/modules/priming/campaigns/{cid}/stop")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "stopped"
    assert body["finished_at"] is not None
