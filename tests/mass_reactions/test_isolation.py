"""Multi-tenancy масс-реакций: кампании изолированы по владельцу."""

from __future__ import annotations

import itertools

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from core.repositories.account import AccountRepository
from core.schemas.account import AccountCreate

_PHONE = itertools.count(71_000_000_000)


class _FakeQueue:
    async def enqueue(self, name, *args, **kwargs):
        return "job-1"

    async def schedule(self, name, run_at, *args, **kwargs):
        return "job-1"


def _client(session, user: str) -> TestClient:
    from modules.mass_reactions.api.router import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: user
    app.dependency_overrides[get_task_queue] = lambda: _FakeQueue()
    return TestClient(app)


def _make_account(session, user_id: str) -> int:
    acc = AccountRepository(session).create(
        AccountCreate(
            phone=f"+{next(_PHONE)}",
            user_id=user_id,
            session_enc=b"enc",
            device_model="d",
            system_version="v",
            app_version="a",
            lang_code="ru",
            system_lang_code="ru-RU",
        )
    )
    session.commit()
    return acc.id


def _create(client) -> int:
    r = client.post(
        "/modules/mass-reactions/campaigns",
        json={"name": "A", "reaction_emojis": ["👍"]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_campaign_isolated_between_users(session):
    a, b = _client(session, "A"), _client(session, "B")
    cid = _create(a)

    # B не видит кампанию A в списке и получает 404 по прямому id.
    assert all(c["id"] != cid for c in b.get("/modules/mass-reactions/campaigns").json())
    assert b.get(f"/modules/mass-reactions/campaigns/{cid}").status_code == 404
    assert b.patch(
        f"/modules/mass-reactions/campaigns/{cid}", json={"name": "x"}
    ).status_code == 404
    assert b.delete(f"/modules/mass-reactions/campaigns/{cid}").status_code == 404
    assert b.post(f"/modules/mass-reactions/campaigns/{cid}/start").status_code == 404

    # Владелец — видит.
    assert a.get(f"/modules/mass-reactions/campaigns/{cid}").status_code == 200
    assert any(c["id"] == cid for c in a.get("/modules/mass-reactions/campaigns").json())


def test_cannot_attach_other_users_account(session):
    a = _client(session, "A")
    cid = _create(a)
    foreign = _make_account(session, "B")  # аккаунт чужого пользователя

    # A пытается прицепить чужой аккаунт → 404 (как «не найден»).
    r = a.post(
        f"/modules/mass-reactions/campaigns/{cid}/accounts",
        json={"account_ids": [foreign]},
    )
    assert r.status_code == 404

    # Свой аккаунт цепляется нормально.
    own = _make_account(session, "A")
    r = a.post(
        f"/modules/mass-reactions/campaigns/{cid}/accounts",
        json={"account_ids": [own]},
    )
    assert r.status_code == 201, r.text
    assert any(x["account_id"] == own for x in r.json())
