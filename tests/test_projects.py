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
