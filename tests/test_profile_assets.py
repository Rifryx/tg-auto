"""Тесты пула asset'ов и apply_profile_pool (этап 6, backlog #1)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from core.config import get_settings
from core.enums import BulkActionType
from core.models import Account, ProfileAsset
from core.repositories.profile_asset import ProfileAssetRepository
from modules.bulk.actions import ACTION_REGISTRY
from modules.bulk.actions.apply_profile_pool import (
    ApplyProfilePoolPayload,
    _fill_template,
)

pytestmark = pytest.mark.asyncio

_TABLES = (
    "autopilot_actions",
    "autopilot_goals",
    "bulk_job_items",
    "bulk_jobs",
    "profile_assets",
    "accounts",
    "projects",
    "account_status_history",
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


class _Ctx:
    def __init__(self, s):
        self._s = s

    def __enter__(self):
        return self._s

    def __exit__(self, *exc):
        return False


# ── repo tests ──────────────────────────────────────────────────────────────


def test_pick_random_returns_none_when_empty(session):
    _clean(session)
    got = ProfileAssetRepository(session).pick_random(kind="first_name")
    assert got is None


def test_pick_random_by_kind(session):
    _clean(session)
    session.add(ProfileAsset(user_id="u1", kind="first_name", value="Alice", tags=[]))
    session.add(ProfileAsset(user_id="u1", kind="last_name", value="Bond", tags=[]))
    session.commit()

    got = ProfileAssetRepository(session).pick_random(kind="first_name")
    assert got is not None
    assert got.kind == "first_name"
    assert got.value == "Alice"


def test_pick_random_filters_by_tags_any(session):
    _clean(session)
    session.add(ProfileAsset(user_id="u1", kind="bio", value="A", tags=["ru"]))
    session.add(ProfileAsset(user_id="u1", kind="bio", value="B", tags=["en"]))
    session.add(ProfileAsset(user_id="u1", kind="bio", value="C", tags=["fr"]))
    session.commit()

    got = ProfileAssetRepository(session).pick_random(kind="bio", tags_any=["en", "fr"])
    assert got is not None
    assert got.value in {"B", "C"}


def test_pick_random_increments_used_count(session):
    _clean(session)
    session.add(ProfileAsset(user_id="u1", kind="first_name", value="Alice", tags=[]))
    session.commit()
    before = session.execute(
        text("SELECT used_count FROM profile_assets WHERE value='Alice'")
    ).scalar_one()
    ProfileAssetRepository(session).pick_random(kind="first_name")
    session.commit()
    after = session.execute(
        text("SELECT used_count FROM profile_assets WHERE value='Alice'")
    ).scalar_one()
    assert after == before + 1


def test_check_constraints_reject_wrong_kind(session):
    from sqlalchemy.exc import IntegrityError

    _clean(session)
    session.add(ProfileAsset(user_id="u1", kind="bad", value="X", tags=[]))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_check_constraints_require_content(session):
    from sqlalchemy.exc import IntegrityError

    _clean(session)
    session.add(ProfileAsset(user_id="u1", kind="first_name", tags=[]))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ── apply_profile_pool ──────────────────────────────────────────────────────


def test_username_template_fills_n():
    import random
    rng = random.Random(1)
    result = _fill_template("john_{n}", rng)
    assert result.startswith("john_")
    assert result[len("john_"):].isdigit()


def test_pool_action_registered():
    """Registration side-effect: apply_profile_pool лежит в реестре."""
    assert BulkActionType.APPLY_PROFILE_POOL.value in ACTION_REGISTRY
    action = ACTION_REGISTRY[BulkActionType.APPLY_PROFILE_POOL.value]
    assert action.requires_client is True
    assert action.governor_key == "bulk_profile"


async def test_pool_action_skipped_when_pool_empty(session):
    """Если во всём пуле ничего не подошло — item уходит в skipped."""
    _clean(session)
    account = Account(
        phone="+79990000001", session_enc=b"e",
        device_model="d", system_version="v",
        app_version="a", lang_code="uk", system_lang_code="uk-UA",
    )
    session.add(account)
    session.flush()
    session.commit()

    action = ACTION_REGISTRY[BulkActionType.APPLY_PROFILE_POOL.value]
    payload = ApplyProfilePoolPayload(first_name_tags=["ru"])
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=None,  # без клиента не должно дойти, т.к. skipped на пусто
    )
    assert result.ok is False
    assert result.skipped is True
    assert result.detail["reason"] == "empty_pool_match"


def test_payload_validates_all_optional():
    """Все поля payload'а необязательны — payload может быть пустым (item потом skip)."""
    p = ApplyProfilePoolPayload()
    assert p.username_from_pool is False
