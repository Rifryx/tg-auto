"""API диалогов аккаунта (#5): список из Redis-снапшота, sync/leave в очередь."""
from __future__ import annotations

import itertools
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.services.monitoring as monitoring
from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from api.routers import accounts as accounts_router
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from core.schemas.account import AccountCreate

_PHONE = itertools.count(79_000_100_200)


class _SpyQueue:
    def __init__(self):
        self.enqueued: list[tuple] = []

    async def enqueue(self, task_name, *args, **kwargs):
        self.enqueued.append((task_name, args))
        return "job-1"


class _FakeCache:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)


def _make_account(session) -> int:
    acc = AccountRepository(session).create(
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
    return acc.id


@pytest.fixture
def ctx(session, monkeypatch):
    spy = _SpyQueue()
    cache = _FakeCache()
    monkeypatch.setattr(monitoring, "get_cache_redis", lambda: cache)
    app = FastAPI()
    app.include_router(accounts_router.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_task_queue] = lambda: spy
    app.dependency_overrides[require_user] = lambda: "u"
    return TestClient(app), spy, cache


def test_list_dialogs_empty_when_not_synced(ctx, session):
    client, _spy, _cache = ctx
    aid = _make_account(session)
    r = client.get(f"/accounts/{aid}/dialogs")
    assert r.status_code == 200
    body = r.json()
    assert body["synced"] is False and body["items"] == []


def test_list_dialogs_returns_snapshot(ctx, session):
    client, _spy, cache = ctx
    aid = _make_account(session)
    cache.store[f"account:{aid}:dialogs"] = json.dumps(
        {
            "items": [
                {"id": 111, "kind": "channel", "title": "Durov", "username": "durov",
                 "members": 100, "is_creator": False}
            ],
            "synced_at": "2026-10-17T00:00:00+00:00",
        }
    )
    r = client.get(f"/accounts/{aid}/dialogs")
    body = r.json()
    assert body["synced"] is True
    assert body["items"][0]["title"] == "Durov"


def test_sync_queues_task(ctx, session):
    client, spy, _cache = ctx
    aid = _make_account(session)
    r = client.post(f"/accounts/{aid}/dialogs/sync")
    assert r.status_code == 202
    assert any(n == TaskName.ACCOUNT_SYNC_DIALOGS for n, _ in spy.enqueued)


def test_leave_requires_ids_or_all(ctx, session):
    client, _spy, _cache = ctx
    aid = _make_account(session)
    assert client.post(f"/accounts/{aid}/dialogs/leave", json={}).status_code == 400


def test_leave_all_and_selected_queue_task(ctx, session):
    client, spy, _cache = ctx
    aid = _make_account(session)
    assert client.post(f"/accounts/{aid}/dialogs/leave", json={"all": True}).status_code == 202
    assert client.post(
        f"/accounts/{aid}/dialogs/leave", json={"dialog_ids": [111]}
    ).status_code == 202
    leaves = [args for n, args in spy.enqueued if n == TaskName.ACCOUNT_LEAVE_DIALOGS]
    assert leaves[0] == (aid, None)  # all → None
    assert leaves[1] == (aid, [111])
