"""Реактивный путь active-проб: Telethon-ошибка → корректный partial-payload.

Интеграционные (нужна БД: ``around_telethon_call`` записывает HealthEvent и
переводит state machine). Сеть не поднимается — клиент фейковый.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from telethon.errors import (
    AuthKeyUnregisteredError,
    PhoneNumberBannedError,
    SessionRevokedError,
)

from core.models import Account
from core.repositories.account import AccountRepository
from worker.health.probes import probe_session

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)

_TABLES = (
    "accounts",
    "proxies",
    "health_events",
    "account_health",
    "account_status_history",
    "warming_activities",
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
)
_PHONE = iter(range(80_000_000_000, 80_001_000_000))


class _Req:
    pass


class _FakeUser:
    def __init__(self, username=None, photo=None):
        self.username = username
        self.photo = photo


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


def _make_account(session) -> int:
    acc = Account(
        phone=f"+{next(_PHONE)}",
        session_enc=b"enc",
        status="pool",
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    session.add(acc)
    session.flush()
    session.commit()
    return acc.id


class _AuthKeyClient:
    async def get_me(self):
        raise AuthKeyUnregisteredError(request=_Req())


class _SessionRevokedClient:
    async def get_me(self):
        raise SessionRevokedError(request=_Req())


class _PhoneBannedClient:
    async def get_me(self):
        raise PhoneNumberBannedError(request=_Req())


class _AliveClient:
    async def get_me(self):
        return _FakeUser(username="alice", photo=object())


# --- session_alive=False через AuthKeyUnregistered ---------------------------


async def test_probe_session_marks_dead_on_auth_key_unregistered(session):
    _clean(session)
    account_id = _make_account(session)

    payload = await probe_session(
        _AuthKeyClient(),
        account_id=account_id,
        session_factory=_factory(session),
        now=NOW,
    )
    assert payload["session_alive"] is False
    assert payload["last_session_check_at"] == NOW

    # Монитор автоматом перевёл акк в banned и оставил health_event.
    account = AccountRepository(session).get(account_id)
    assert account.status == "banned"


# --- session_alive=False через SessionRevoked -------------------------------


async def test_probe_session_marks_dead_on_session_revoked(session):
    _clean(session)
    account_id = _make_account(session)

    payload = await probe_session(
        _SessionRevokedClient(),
        account_id=account_id,
        session_factory=_factory(session),
        now=NOW,
    )
    assert payload["session_alive"] is False


# --- Phone banned → phone_status=banned + session_alive=False ---------------


async def test_probe_session_marks_phone_banned(session):
    _clean(session)
    account_id = _make_account(session)

    payload = await probe_session(
        _PhoneBannedClient(),
        account_id=account_id,
        session_factory=_factory(session),
        now=NOW,
    )
    assert payload["session_alive"] is False
    assert payload["phone_status"] == "banned"
    assert payload["last_phone_check_at"] == NOW


# --- Успех: get_me отдаёт живого юзера --------------------------------------


async def test_probe_session_marks_alive_on_success(session):
    _clean(session)
    account_id = _make_account(session)

    payload = await probe_session(
        _AliveClient(),
        account_id=account_id,
        session_factory=_factory(session),
        now=NOW,
    )
    assert payload["session_alive"] is True
    assert payload["last_seen_alive_at"] == NOW
