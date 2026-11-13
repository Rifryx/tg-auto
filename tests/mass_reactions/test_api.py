"""Шаг 5: API масс-реакций — CRUD, чаты, аккаунты, lifecycle."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps.auth import require_user
from api.deps.db import get_session
from modules.mass_reactions.api.router import router


def _client(session) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: "user-1"
    return TestClient(app)


def _create(client, **over) -> dict:
    body = {"name": "Кампания 1", "reaction_emojis": ["👍", "🔥"]}
    body.update(over)
    r = client.post("/modules/mass-reactions/campaigns", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_list_get(session):
    client = _client(session)
    created = _create(client)
    assert created["status"] == "draft"
    assert created["reaction_emojis"] == ["👍", "🔥"]
    assert created["every_n_message"] == 1

    lst = client.get("/modules/mass-reactions/campaigns").json()
    assert any(c["id"] == created["id"] for c in lst)

    got = client.get(f"/modules/mass-reactions/campaigns/{created['id']}")
    assert got.status_code == 200
    assert got.json()["name"] == "Кампания 1"


def test_empty_emojis_rejected_by_schema(session):
    client = _client(session)
    r = client.post(
        "/modules/mass-reactions/campaigns",
        json={"name": "x", "reaction_emojis": []},
    )
    assert r.status_code == 422


def test_update_only_in_editable_status(session):
    client = _client(session)
    c = _create(client)
    # draft → редактируемо.
    r = client.patch(
        f"/modules/mass-reactions/campaigns/{c['id']}",
        json={"every_n_message": 3, "probability_percent": 50},
    )
    assert r.status_code == 200
    assert r.json()["every_n_message"] == 3

    # start → running → редактирование запрещено (409).
    assert client.post(f"/modules/mass-reactions/campaigns/{c['id']}/start").status_code == 200
    r2 = client.patch(
        f"/modules/mass-reactions/campaigns/{c['id']}", json={"every_n_message": 5}
    )
    assert r2.status_code == 409


def test_add_chats_and_list(session):
    client = _client(session)
    c = _create(client)
    r = client.post(
        f"/modules/mass-reactions/campaigns/{c['id']}/chats",
        json={"raw_text": "@a\n@b, @a", "notify_mode": "notify_and_join"},
    )
    assert r.status_code == 201
    chats = r.json()
    assert [ch["chat_ref"] for ch in chats] == ["a", "b"]
    assert all(ch["notify_mode"] == "notify_and_join" for ch in chats)

    listed = client.get(f"/modules/mass-reactions/campaigns/{c['id']}/chats").json()
    assert len(listed) == 2


def test_lifecycle_start_pause_stop(session):
    client = _client(session)
    c = _create(client)
    cid = c["id"]
    assert client.post(f"/modules/mass-reactions/campaigns/{cid}/start").json()["status"] == "running"
    assert client.post(f"/modules/mass-reactions/campaigns/{cid}/pause").json()["status"] == "paused"
    assert client.post(f"/modules/mass-reactions/campaigns/{cid}/stop").json()["status"] == "stopped"
    # stopped → удаляемо.
    assert client.delete(f"/modules/mass-reactions/campaigns/{cid}").status_code == 204
