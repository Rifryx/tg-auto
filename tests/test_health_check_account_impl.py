"""Интеграционный тест reactive-пути check_account_impl (этап 4).

Проверяет: пришла Telethon-ошибка (PhoneNumberBanned) → монитор внутри
``probe_session`` записал HealthEvent + перевёл акк в ``banned``. Проходит
через настоящий ``check_account_impl`` (client_pool + probe вместе), а не
через прямой вызов ``probe_session``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text
from telethon.errors import PhoneNumberBannedError

from core.config import get_settings
from core.models import Account, HealthEvent
from core.repositories.account import AccountRepository
from worker.tasks.health import check_account_impl

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)

_TABLES = (
    "autopilot_actions",
    "autopilot_goals",
    "accounts",
    "projects",
    "ban_risk_snapshots",
    "account_health",
    "health_events",
    "account_status_history",
    "warming_activities",
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


class _Ctx:
    def __init__(self, session):
        self._s = session

    def __enter__(self):
        return self._s

    def __exit__(self, *exc):
        return False


class _Req:
    pass


class _BannedClient:
    """Telethon-клиент, у которого ЛЮБОЙ get_me бросает PhoneNumberBannedError."""

    async def get_me(self):
        raise PhoneNumberBannedError(request=_Req())


class _FakePool:
    def __init__(self, client):
        self._client = client
        self.gets = 0
        self.releases = 0

    async def get(self, account_id):
        self.gets += 1
        return self._client

    async def release(self, account_id):
        self.releases += 1


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _make_account(session, phone="+79990000001", status="pool"):
    acc = Account(
        phone=phone,
        session_enc=b"enc",
        status=status,
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


async def test_check_account_impl_bans_account_on_phone_number_banned(session):
    """Полный reactive-путь: probe_session ловит PhoneNumberBannedError,
    монитор пишет HealthEvent + переводит акк в banned. Клиент из пула
    берётся ровно один раз и корректно отпускается."""
    _clean(session)
    account_id = _make_account(session, status="pool")

    client = _BannedClient()
    pool = _FakePool(client)
    ctx = {
        "session_factory": lambda: _Ctx(session),
        "client_pool": pool,
        "now": NOW,
    }

    await check_account_impl(ctx, account_id, probes=["session"])

    # 1) Аккаунт переведён в banned через state machine (см. probe_session
    #    ← around_telethon_call → AccountStateMachine.transition).
    session.expire_all()
    account = AccountRepository(session).get(account_id)
    assert account.status == "banned"

    # 2) HealthEvent зафиксирован.
    events = (
        session.execute(select(HealthEvent).where(HealthEvent.account_id == account_id))
        .scalars()
        .all()
    )
    assert len(events) >= 1

    # 3) Клиент из пула был взят и отпущен ровно один раз.
    assert pool.gets == 1
    assert pool.releases == 1
