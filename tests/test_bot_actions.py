"""Проверка владения (ownership) в чат-действиях бота (bot/actions.py).

Ключевой инвариант фичи «управление из чата»: один пользователь не может
трогать аккаунты и кампании другого. Правило:

* Кампания: ``created_by == requester_id`` ИЛИ requester — админ.
* Аккаунт: ``owner_user_id == requester_id`` ИЛИ requester — админ.
  ``owner_user_id IS NULL`` (общий/legacy-пул) — только админ.

Нарушение владения выглядит как «не найдено» (:class:`NotOwned`).

Тесты работают с реальной БД (postgres_test, фикстура ``session``); слой
прайминга тянет telethon/structlog — если их нет, скипаем целиком.
"""

from __future__ import annotations

import itertools

import pytest

pytest.importorskip("structlog")
pytest.importorskip("telethon")

from core.models import Account
from modules.priming.repositories import CampaignRepository
from modules.priming.schemas.enums import PrimingCampaignStatus, TriggerAction

from bot import actions

_PHONE = itertools.count(96_000_000_000)

_OWNER = 1001
_OTHER = 2002
_ADMIN = 9009


@pytest.fixture(autouse=True)
def _admin_env(monkeypatch):
    """Фиксируем список админов, чтобы is_admin был детерминированным."""
    monkeypatch.setenv("ADMIN_USER_IDS", str(_ADMIN))
    # Настройки кэшируются через lru_cache — сбрасываем.
    from core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_account(session, *, owner_user_id=None, status="pool") -> Account:
    acc = Account(
        phone=str(next(_PHONE)),
        owner_user_id=owner_user_id,
        session_enc=b"x",
        status=status,
        device_model="P",
        system_version="13",
        app_version="10",
        lang_code="ru",
        system_lang_code="ru-RU",
    )
    session.add(acc)
    session.flush()
    return acc


def _make_campaign(session, *, created_by, status=PrimingCampaignStatus.FINISHED.value):
    return CampaignRepository(session).create(
        {
            "name": "c",
            "trigger_action": TriggerAction.SECRET_CHAT_REQUEST.value,
            "delay_between_targets_sec_min": 60,
            "delay_between_targets_sec_max": 90,
            "daily_limit_per_account": 40,
            "stop_on_privacy_rate": 0.3,
            "status": status,
            "created_by": created_by,
        }
    )


# ── кампании ──────────────────────────────────────────────────────────────────


def test_list_owned_campaigns_filters_by_owner(session):
    _make_campaign(session, created_by=_OWNER)
    _make_campaign(session, created_by=_OTHER)
    session.commit()

    mine = actions.list_owned_campaigns(session, _OWNER)
    assert len(mine) == 1
    assert all(c.created_by == _OWNER for c in mine)


def test_admin_sees_all_campaigns(session):
    _make_campaign(session, created_by=_OWNER)
    _make_campaign(session, created_by=_OTHER)
    session.commit()

    seen = actions.list_owned_campaigns(session, _ADMIN)
    owners = {c.created_by for c in seen}
    assert _OWNER in owners and _OTHER in owners


def test_get_owned_campaign_rejects_foreign(session):
    camp = _make_campaign(session, created_by=_OWNER)
    session.commit()

    # Владелец — ок.
    assert actions.get_owned_campaign(session, camp.id, _OWNER).id == camp.id
    # Чужой — «не найдено».
    with pytest.raises(actions.NotOwned):
        actions.get_owned_campaign(session, camp.id, _OTHER)
    # Админ — ок.
    assert actions.get_owned_campaign(session, camp.id, _ADMIN).id == camp.id


# ── аккаунты ──────────────────────────────────────────────────────────────────


def test_get_owned_account_owner_ok_foreign_rejected(session):
    acc = _make_account(session, owner_user_id=_OWNER)
    session.commit()

    assert actions.get_owned_account(session, acc.id, _OWNER).id == acc.id
    with pytest.raises(actions.NotOwned):
        actions.get_owned_account(session, acc.id, _OTHER)


def test_null_owner_account_only_for_admin(session):
    """Legacy/общий аккаунт (owner IS NULL) — доступен только админу."""
    acc = _make_account(session, owner_user_id=None)
    session.commit()

    with pytest.raises(actions.NotOwned):
        actions.get_owned_account(session, acc.id, _OWNER)
    assert actions.get_owned_account(session, acc.id, _ADMIN).id == acc.id


def test_quarantine_roundtrip(session):
    """RETIRE выводит аккаунт из пула, RESTORE возвращает — обратимо."""
    acc = _make_account(session, owner_user_id=_OWNER, status="pool")
    session.commit()

    out = actions.quarantine_account(session, acc.id, _OWNER)
    assert out.status == "retired"

    back = actions.unquarantine_account(session, acc.id, _OWNER)
    assert back.status == "pool"


def test_quarantine_foreign_account_rejected(session):
    acc = _make_account(session, owner_user_id=_OWNER, status="pool")
    session.commit()

    with pytest.raises(actions.NotOwned):
        actions.quarantine_account(session, acc.id, _OTHER)
