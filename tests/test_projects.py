"""Интеграционные тесты проектов и фильтров аккаунтов (этап 2)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from core.config import get_settings
from core.enums import AccountRole
from core.models import Account, Project
from core.repositories.account import AccountRepository
from core.repositories.project import ProjectRepository

pytestmark = pytest.mark.asyncio

_TABLES = (
    "autopilot_actions",
    "autopilot_goals",
    "accounts",
    "projects",
    "ban_risk_snapshots",
    "account_status_history",
    "warming_activities",
    "health_events",
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _make_account(session, phone, **fields):
    acc = Account(
        phone=phone,
        session_enc=b"enc",
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
        **fields,
    )
    session.add(acc)
    session.flush()
    session.commit()
    return acc


# ── projects repo ───────────────────────────────────────────────────────────


async def test_create_and_list_projects(session):
    _clean(session)
    repo = ProjectRepository(session)
    p1 = repo.create(user_id="u1", name="Проект A", description="desc")
    p2 = repo.create(user_id="u1", name="Проект B")
    p3 = repo.create(user_id="u2", name="Чужой")
    session.commit()

    got = repo.list_for_user("u1")
    assert {p.id for p in got} == {p1.id, p2.id}
    assert p3.id not in {p.id for p in got}


async def test_project_unique_by_user_name(session):
    from sqlalchemy.exc import IntegrityError

    _clean(session)
    repo = ProjectRepository(session)
    repo.create(user_id="u1", name="dup")
    session.commit()
    with pytest.raises(IntegrityError):
        repo.create(user_id="u1", name="dup")
        session.commit()
    session.rollback()
    # Другому пользователю то же имя разрешено:
    repo.create(user_id="u2", name="dup")
    session.commit()


async def test_delete_project_nulls_out_account_link(session):
    _clean(session)
    repo = ProjectRepository(session)
    project = repo.create(user_id="u1", name="P")
    session.commit()
    account = _make_account(session, "+1", project_id=project.id)

    assert repo.delete(project.id) is True
    session.commit()
    session.refresh(account)
    assert account.project_id is None


# ── accounts: filter by project / role / tag ────────────────────────────────


async def test_list_filtered_by_project(session):
    _clean(session)
    project = Project(user_id="u1", name="P")
    session.add(project)
    session.commit()

    a1 = _make_account(session, "+1", project_id=project.id)
    a2 = _make_account(session, "+2", project_id=project.id)
    a3 = _make_account(session, "+3", project_id=None)  # без проекта

    repo = AccountRepository(session)
    in_project = repo.list_filtered(project_id=project.id)
    without_project = repo.list_filtered(project_id=0)

    assert {a.id for a in in_project} == {a1.id, a2.id}
    assert {a.id for a in without_project} == {a3.id}


async def test_list_filtered_by_role(session):
    _clean(session)
    _make_account(session, "+1", role=AccountRole.MAIN.value)
    _make_account(session, "+2", role=AccountRole.BURNER.value)
    _make_account(session, "+3")  # role NULL

    repo = AccountRepository(session)
    mains = repo.list_filtered(role=AccountRole.MAIN.value)
    assert len(mains) == 1
    assert mains[0].role == "main"


async def test_list_filtered_by_tag(session):
    _clean(session)
    _make_account(session, "+1", tags=["vip", "seo"])
    _make_account(session, "+2", tags=["seo"])
    _make_account(session, "+3", tags=[])

    repo = AccountRepository(session)
    vip = repo.list_filtered(tag="vip")
    seo = repo.list_filtered(tag="seo")

    assert {a.phone for a in vip} == {"+1"}
    assert {a.phone for a in seo} == {"+1", "+2"}


async def test_role_check_constraint_blocks_invalid(session):
    """CHECK role_allowed не пускает произвольные значения."""
    from sqlalchemy.exc import IntegrityError

    _clean(session)
    with pytest.raises(IntegrityError):
        _make_account(session, "+1", role="godlike")


# ── PUT /projects/{id}/accounts: состав группы одной транзакцией ────────────


def _client(session, user="u1"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.deps.auth import require_user
    from api.deps.db import get_session
    from api.routers.projects import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)


async def test_set_members_assigns_moves_and_detaches(session):
    _clean(session)
    repo = ProjectRepository(session)
    group_a = repo.create(user_id="u1", name="A")
    group_b = repo.create(user_id="u1", name="B")
    session.commit()
    stays = _make_account(session, "+1", project_id=group_a.id)
    leaves = _make_account(session, "+2", project_id=group_a.id)
    moved_in = _make_account(session, "+3", project_id=group_b.id)
    free = _make_account(session, "+4")

    resp = _client(session).put(
        f"/projects/{group_a.id}/accounts",
        json={"account_ids": [stays.id, moved_in.id, free.id]},
    )
    assert resp.status_code == 200
    for acc in (stays, leaves, moved_in, free):
        session.refresh(acc)
    assert stays.project_id == group_a.id
    assert leaves.project_id is None
    # аккаунт в одной группе: из B переехал в A
    assert moved_in.project_id == group_a.id
    assert free.project_id == group_a.id


async def test_set_members_empty_clears_group(session):
    _clean(session)
    group = ProjectRepository(session).create(user_id="u1", name="A")
    session.commit()
    acc = _make_account(session, "+1", project_id=group.id)

    resp = _client(session).put(f"/projects/{group.id}/accounts", json={"account_ids": []})
    assert resp.status_code == 200
    session.refresh(acc)
    assert acc.project_id is None


async def test_set_members_rejects_unknown_account_and_foreign_group(session):
    _clean(session)
    repo = ProjectRepository(session)
    mine = repo.create(user_id="u1", name="mine")
    foreign = repo.create(user_id="u2", name="theirs")
    session.commit()

    resp = _client(session).put(f"/projects/{mine.id}/accounts", json={"account_ids": [999]})
    assert resp.status_code == 422
    resp = _client(session).put(f"/projects/{foreign.id}/accounts", json={"account_ids": []})
    assert resp.status_code == 404
