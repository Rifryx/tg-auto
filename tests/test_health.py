"""Тесты health-монитора и governor (PROJECT-STAGES §5.3).

Монитор/прокси-чек — на настоящей БД (Telethon-ошибки эмулируются, сети нет).
Governor — на fakeredis (TTL и «fake clock» через патч time.time).
Таблицы чистятся в начале каждого теста.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fakeredis import aioredis as fake_aioredis
from sqlalchemy import func, select, text
from telethon.errors import (
    FloodWaitError,
    PhoneNumberBannedError,
    SessionRevokedError,
    UserDeactivatedBanError,
)

from core.models import Account, HealthEvent, Proxy
from core.repositories.account import AccountRepository
from worker.health import Governor, around_telethon_call
from worker.tasks.handlers import cooldown_return_impl
from worker.tasks.health import check_proxies_impl

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

_TABLES = (
    "accounts",
    "proxies",
    "health_events",
    "account_status_history",
    "warming_activities",
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
)
_PHONE = iter(range(90_000_000_000, 90_001_000_000))


class _Req:
    pass


class _SpyPublisher:
    def __init__(self):
        self.events = []

    def publish(self, channel, payload):
        self.events.append((channel, dict(payload)))


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


def _make_proxy(session, *, status="alive") -> int:
    proxy = Proxy(host="10.0.0.1", port=1080, type="socks5", status=status)
    session.add(proxy)
    session.flush()
    session.commit()
    return proxy.id


def _make_account(session, *, status, proxy_id=None, previous_status=None, cooldown_until=None) -> int:
    acc = Account(
        phone=f"+{next(_PHONE)}",
        session_enc=b"enc",
        status=status,
        proxy_id=proxy_id,
        previous_status=previous_status,
        cooldown_until=cooldown_until,
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


def _events(session, account_id, event_type):
    return session.execute(
        select(HealthEvent).where(
            HealthEvent.account_id == account_id,
            HealthEvent.event_type == event_type,
        )
    ).scalars().all()


# --- 1. FloodWait → cooldown -------------------------------------------------


async def test_flood_wait_puts_account_into_cooldown(session):
    _clean(session)
    account_id = _make_account(session, status="pool")

    async def call():
        raise FloodWaitError(request=_Req(), capture=60)

    with pytest.raises(FloodWaitError):
        await around_telethon_call(
            call, account_id=account_id, session_factory=_factory(session), now=NOW
        )

    events = _events(session, account_id, "flood_wait")
    assert len(events) == 1
    assert events[0].meta == {"seconds": 60}

    account = AccountRepository(session).get(account_id)
    assert account.status == "cooldown"
    assert account.previous_status == "pool"
    assert account.cooldown_until == NOW + timedelta(seconds=60)


# --- 2. cooldown_return возвращает в previous_status -------------------------


async def test_cooldown_return_restores_previous_status(session):
    _clean(session)
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    account_id = _make_account(
        session, status="cooldown", previous_status="pool", cooldown_until=past
    )

    returned = await cooldown_return_impl({"session_factory": _factory(session), "publisher": None})

    assert account_id in returned
    account = AccountRepository(session).get(account_id)
    assert account.status == "pool"
    assert account.cooldown_until is None
    assert account.previous_status is None


# --- 3. SessionRevoked → banned ---------------------------------------------


async def test_session_revoked_bans_account(session):
    _clean(session)
    account_id = _make_account(session, status="pool")

    async def call():
        raise SessionRevokedError(request=_Req())

    with pytest.raises(SessionRevokedError):
        await around_telethon_call(
            call, account_id=account_id, session_factory=_factory(session), now=NOW
        )

    assert len(_events(session, account_id, "session_revoked")) == 1
    assert AccountRepository(session).get(account_id).status == "banned"


# --- 3b. Бан при логине: PhoneNumberBanned из created → banned (#8) ----------


async def test_phone_number_banned_bans_created_account(session):
    """Бан-ошибка логина фиксирует HealthEvent и банит аккаунт из 'created'.

    Раньше (без обёртки login-вызовов) это падало как generic failed — без
    HealthEvent и без перехода в banned.
    """
    _clean(session)
    account_id = _make_account(session, status="created")

    async def call():
        raise PhoneNumberBannedError(request=_Req())

    with pytest.raises(PhoneNumberBannedError):
        await around_telethon_call(
            call,
            account_id=account_id,
            session_factory=_factory(session),
            now=NOW,
            handle_flood_wait=False,
        )

    assert len(_events(session, account_id, "session_revoked")) == 1
    assert AccountRepository(session).get(account_id).status == "banned"


# --- 3c. Бан при прогреве: UserDeactivatedBan из warming → banned (#8) -------


async def test_user_deactivated_ban_bans_warming_account(session):
    _clean(session)
    account_id = _make_account(session, status="warming")

    async def call():
        raise UserDeactivatedBanError(request=_Req())

    with pytest.raises(UserDeactivatedBanError):
        await around_telethon_call(
            call, account_id=account_id, session_factory=_factory(session), now=NOW
        )

    assert len(_events(session, account_id, "session_revoked")) == 1
    assert AccountRepository(session).get(account_id).status == "banned"


# --- 3d. Регрессия #4: handle_flood_wait=False пропускает флудвейт нетронутым -


async def test_flood_wait_not_handled_passes_through_without_incident(session):
    _clean(session)
    account_id = _make_account(session, status="pool")

    async def call():
        raise FloodWaitError(request=_Req(), capture=60)

    with pytest.raises(FloodWaitError):
        await around_telethon_call(
            call,
            account_id=account_id,
            session_factory=_factory(session),
            now=NOW,
            handle_flood_wait=False,
        )

    # ни HealthEvent, ни cooldown — флудвейт разбирает вызывающий (login-flow)
    assert _events(session, account_id, "flood_wait") == []
    assert AccountRepository(session).get(account_id).status == "pool"


# --- 3e. HealthEvent публикует health_alert в pub/sub (#9) -------------------


async def test_incident_publishes_health_alert(session):
    _clean(session)
    account_id = _make_account(session, status="pool")
    pub = _SpyPublisher()

    async def call():
        raise FloodWaitError(request=_Req(), capture=30)

    with pytest.raises(FloodWaitError):
        await around_telethon_call(
            call,
            account_id=account_id,
            session_factory=_factory(session),
            publisher=pub,
            now=NOW,
        )

    alerts = [p for ch, p in pub.events if ch == "health_alert"]
    assert alerts == [
        {"account_id": account_id, "event_type": "flood_wait", "severity": "warning"}
    ]


async def test_ban_publishes_health_alert(session):
    _clean(session)
    account_id = _make_account(session, status="pool")
    pub = _SpyPublisher()

    async def call():
        raise SessionRevokedError(request=_Req())

    with pytest.raises(SessionRevokedError):
        await around_telethon_call(
            call,
            account_id=account_id,
            session_factory=_factory(session),
            publisher=pub,
            now=NOW,
        )

    alerts = [p for ch, p in pub.events if ch == "health_alert"]
    assert alerts == [
        {"account_id": account_id, "event_type": "session_revoked", "severity": "critical"}
    ]


# --- 4. governor: 20 ок, 21-й — нет ------------------------------------------


async def test_governor_hourly_comment_limit():
    redis = fake_aioredis.FakeRedis()
    gov = Governor(redis)
    results = [await gov.check_and_reserve(1, "comment") for _ in range(20)]
    assert all(results)
    assert await gov.check_and_reserve(1, "comment") is False
    await redis.aclose()


# --- 5. governor: TTL и сброс через час (fake clock) -------------------------


async def test_governor_ttl_resets_after_window():
    redis = fake_aioredis.FakeRedis()
    gov = Governor(redis)

    assert await gov.check_and_reserve(7, "comment") is True
    ttl = await redis.ttl("rl:acc:7:comment:hour")
    assert 0 < ttl <= 3600

    base = datetime.now(timezone.utc).timestamp()
    with mock.patch("time.time", lambda: base + 3700):
        # час прошёл — счётчик часового окна сброшен
        assert await redis.get("rl:acc:7:comment:hour") is None
        assert await gov.check_and_reserve(7, "comment") is True
        assert int(await redis.get("rl:acc:7:comment:hour")) == 1
    await redis.aclose()


# --- 6. dead-прокси → HealthEvent(proxy_down), статус не меняется -------------


async def test_dead_proxy_records_event_without_status_change(session):
    _clean(session)
    proxy_id = _make_proxy(session, status="alive")
    account_id = _make_account(session, status="assigned", proxy_id=proxy_id)

    ctx = {
        "session_factory": _factory(session),
        "now": NOW,
        "proxy_prober": lambda proxy: False,  # мёртвый прокси
    }
    result = await check_proxies_impl(ctx)

    assert proxy_id in result["dead"]
    session.expire_all()
    assert session.get(Proxy, proxy_id).status == "dead"
    assert len(_events(session, account_id, "proxy_down")) == 1
    # статус аккаунта не тронут
    assert AccountRepository(session).get(account_id).status == "assigned"
