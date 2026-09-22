"""Тесты новых CHECK constraint'ов (backlog #прочее).

* health_events.triggered_status_change ∈ (NULL, cooldown, banned, retired)
* accounts.previous_status ∈ (NULL, pool, assigned)
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from core.config import get_settings
from core.enums import TriggeredStatusChange
from core.models import Account, HealthEvent


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _clean(session):
    session.execute(
        text(
            "TRUNCATE autopilot_actions, autopilot_goals, project_channels, "
            "bulk_job_items, bulk_jobs, accounts, projects, health_events "
            "RESTART IDENTITY CASCADE"
        )
    )
    session.commit()


def _make_account(session, phone="+700000001"):
    a = Account(
        phone=phone, session_enc=b"e", status="pool",
        device_model="d", system_version="v", app_version="a",
        lang_code="uk", system_lang_code="uk-UA",
    )
    session.add(a)
    session.flush()
    session.commit()
    return a


# ── triggered_status_change ────────────────────────────────────────────────


def test_triggered_status_change_null_ok(session):
    _clean(session)
    account = _make_account(session)
    ev = HealthEvent(
        account_id=account.id, event_type="flood_wait",
        triggered_status_change=None,
    )
    session.add(ev)
    session.commit()  # не роняет


def test_triggered_status_change_valid_values_ok(session):
    _clean(session)
    account = _make_account(session)
    for value in TriggeredStatusChange:
        ev = HealthEvent(
            account_id=account.id, event_type="flood_wait",
            triggered_status_change=value.value,
        )
        session.add(ev)
    session.commit()


def test_triggered_status_change_rejects_garbage(session):
    _clean(session)
    account = _make_account(session)
    ev = HealthEvent(
        account_id=account.id, event_type="flood_wait",
        triggered_status_change="pool→cooldown",  # legacy freeform
    )
    session.add(ev)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_triggered_status_change_rejects_arbitrary(session):
    _clean(session)
    account = _make_account(session)
    ev = HealthEvent(
        account_id=account.id, event_type="flood_wait",
        triggered_status_change="foo",
    )
    session.add(ev)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ── previous_status ────────────────────────────────────────────────────────


def test_previous_status_null_ok(session):
    _clean(session)
    a = Account(
        phone="+700000002", session_enc=b"e", status="pool",
        previous_status=None,
        device_model="d", system_version="v", app_version="a",
        lang_code="uk", system_lang_code="uk-UA",
    )
    session.add(a)
    session.commit()


def test_previous_status_pool_or_assigned_ok(session):
    _clean(session)
    a1 = Account(
        phone="+700000003", session_enc=b"e", status="cooldown",
        previous_status="pool",
        device_model="d", system_version="v", app_version="a",
        lang_code="uk", system_lang_code="uk-UA",
    )
    a2 = Account(
        phone="+700000004", session_enc=b"e", status="cooldown",
        previous_status="assigned",
        device_model="d", system_version="v", app_version="a",
        lang_code="uk", system_lang_code="uk-UA",
    )
    session.add_all([a1, a2])
    session.commit()


def test_previous_status_rejects_junk(session):
    """Пул и assigned — единственные валидные target'ы возврата из cooldown."""
    _clean(session)
    a = Account(
        phone="+700000005", session_enc=b"e", status="pool",
        previous_status="warming",  # ← не должно быть
        device_model="d", system_version="v", app_version="a",
        lang_code="uk", system_lang_code="uk-UA",
    )
    session.add(a)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_previous_status_rejects_arbitrary_string(session):
    _clean(session)
    a = Account(
        phone="+700000006", session_enc=b"e", status="pool",
        previous_status="garbage",
        device_model="d", system_version="v", app_version="a",
        lang_code="uk", system_lang_code="uk-UA",
    )
    session.add(a)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ── enum shape ────────────────────────────────────────────────────────────


def test_enum_has_expected_values():
    assert {t.value for t in TriggeredStatusChange} == {"cooldown", "banned", "retired"}
