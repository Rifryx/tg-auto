"""Интеграционные тесты health-задач и API (этап 4 УТП).

Проходят с реальной Postgres (session-фикстура). Telethon подменяется fake-клиентом,
сеть не поднимается. Пробы возвращают детерминированные payload'ы, чтобы можно было
проверить агрегатор ``check_account_impl`` + ``recompute_score_impl``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import text

from core.models import Account, AccountHealth, HealthEvent, Proxy
from core.repositories.account_health import AccountHealthRepository
from worker.tasks.health import (
    HEALTH_SNAPSHOT_CHANNEL,
    check_account_impl,
    check_accounts_periodic_impl,
    recompute_score_impl,
)

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
_PHONE = iter(range(70_000_000_000, 70_001_000_000))


class _SpyPublisher:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def publish(self, channel, payload):
        self.events.append((channel, dict(payload)))


class _FakeClient:
    """Не делает сеть. Отдаёт то, что подсунет фикстура."""


class _FakeClientPool:
    def __init__(self, client):
        self._client = client
        self.get_calls = 0
        self.release_calls = 0

    async def get(self, account_id: int):
        self.get_calls += 1
        return self._client

    async def release(self, account_id: int):
        self.release_calls += 1


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


def _make_account(session, *, status="pool", proxy_id=None) -> int:
    acc = Account(
        phone=f"+{next(_PHONE)}",
        session_enc=b"enc",
        status=status,
        proxy_id=proxy_id,
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


# --- 1. Snapshot автоматически создаётся при recompute ------------------------


async def test_recompute_creates_snapshot_and_returns_score(session, monkeypatch):
    _clean(session)
    proxy_id = _make_proxy(session, status="alive")
    account_id = _make_account(session, proxy_id=proxy_id)

    publisher = _SpyPublisher()
    ctx = {
        "session_factory": _factory(session),
        "publisher": publisher,
        "now": NOW,
    }
    score = await recompute_score_impl(ctx, account_id)

    snap = AccountHealthRepository(session).get(account_id)
    assert snap is not None
    assert snap.health_score == score
    assert score == 90  # -10 за age_lt_3d (свежий аккаунт, age_days < 3)

    # pub/sub-событие ушло
    assert publisher.events[-1][0] == HEALTH_SNAPSHOT_CHANNEL
    assert publisher.events[-1][1]["account_id"] == account_id
    assert publisher.events[-1][1]["score"] == 90


# --- 2. Мёртвая сессия → score 0 ---------------------------------------------


async def test_dead_session_yields_zero_score(session, monkeypatch):
    _clean(session)
    proxy_id = _make_proxy(session, status="alive")
    account_id = _make_account(session, proxy_id=proxy_id)

    # Патчим пробы: session говорит «мертва», profile не вызывается.
    async def fake_session_probe(*a, **kw):
        return {
            "session_alive": False,
            "last_session_check_at": NOW,
        }

    async def fake_profile_probe(*a, **kw):
        raise AssertionError("profile probe must be skipped when session is dead")

    monkeypatch.setattr("worker.tasks.health.probe_session", fake_session_probe)
    monkeypatch.setattr("worker.tasks.health.probe_profile", fake_profile_probe)

    publisher = _SpyPublisher()
    ctx = {
        "session_factory": _factory(session),
        "publisher": publisher,
        "client_pool": _FakeClientPool(_FakeClient()),
        "now": NOW,
    }
    result = await check_account_impl(ctx, account_id)
    assert result["score"] == 0

    snap = AccountHealthRepository(session).get(account_id)
    assert snap.session_alive is False
    assert snap.health_score == 0
    assert snap.previous_score == 100


# --- 3. Живая сессия + косметика минус ---------------------------------------


async def test_alive_session_applies_cosmetic_penalties(session, monkeypatch):
    _clean(session)
    proxy_id = _make_proxy(session, status="alive")
    account_id = _make_account(session, proxy_id=proxy_id)

    async def fake_session_probe(*a, **kw):
        return {
            "session_alive": True,
            "last_seen_alive_at": NOW,
            "last_session_check_at": NOW,
        }

    async def fake_profile_probe(*a, **kw):
        return {
            "has_2fa": False,
            "has_username": False,
            "has_avatar": True,
            "has_bio": True,
        }

    monkeypatch.setattr("worker.tasks.health.probe_session", fake_session_probe)
    monkeypatch.setattr("worker.tasks.health.probe_profile", fake_profile_probe)

    ctx = {
        "session_factory": _factory(session),
        "publisher": _SpyPublisher(),
        "client_pool": _FakeClientPool(_FakeClient()),
        "now": NOW,
    }
    result = await check_account_impl(ctx, account_id)
    # no_2fa(10) + no_username(5) = 15; аккаунт свежий (created_at≈now, но
    # NOW отражён — age_days=0 → age_lt_3d(10)). Итого 25 → score=75.
    assert result["score"] == 75

    snap = AccountHealthRepository(session).get(account_id)
    assert snap.has_2fa is False
    assert snap.has_username is False
    assert snap.has_avatar is True
    assert snap.has_bio is True


# --- 4. Мёртвый прокси штрафует, живой — нет ---------------------------------


async def test_dead_proxy_reduces_score(session, monkeypatch):
    _clean(session)
    proxy_id = _make_proxy(session, status="dead")
    account_id = _make_account(session, proxy_id=proxy_id)

    ctx = {
        "session_factory": _factory(session),
        "publisher": _SpyPublisher(),
        "now": NOW,
    }
    score = await recompute_score_impl(ctx, account_id)
    assert score == 70  # -20 за proxy_dead, -10 за age_lt_3d


# --- 5. Периодический планировщик: at-risk шедулится чаще ---------------------


async def test_periodic_scheduler_picks_at_risk_first(session):
    _clean(session)
    proxy_id = _make_proxy(session)

    fresh_ok = _make_account(session, proxy_id=proxy_id, status="pool")
    stale_at_risk = _make_account(session, proxy_id=proxy_id, status="pool")
    fresh_at_risk = _make_account(session, proxy_id=proxy_id, status="pool")

    repo = AccountHealthRepository(session)
    # fresh_ok: score=90, проверяли час назад → не пора.
    repo.get_or_create(fresh_ok)
    session.execute(
        text(
            "UPDATE account_health SET health_score=90, last_full_check_at=:t "
            "WHERE account_id=:a"
        ),
        {"t": NOW - timedelta(hours=1), "a": fresh_ok},
    )
    # stale_at_risk: score=30, last_check 4ч назад → пора (риск-порог 3ч).
    repo.get_or_create(stale_at_risk)
    session.execute(
        text(
            "UPDATE account_health SET health_score=30, last_full_check_at=:t "
            "WHERE account_id=:a"
        ),
        {"t": NOW - timedelta(hours=4), "a": stale_at_risk},
    )
    # fresh_at_risk: score=30, но проверяли 1ч назад → ещё не пора.
    repo.get_or_create(fresh_at_risk)
    session.execute(
        text(
            "UPDATE account_health SET health_score=30, last_full_check_at=:t "
            "WHERE account_id=:a"
        ),
        {"t": NOW - timedelta(hours=1), "a": fresh_at_risk},
    )
    session.commit()

    scheduled: list[int] = []

    class _FakeQueue:
        def __init__(self, redis):
            pass

        async def enqueue(self, name, *args, **kwargs):
            scheduled.append(args[0])
            return f"job-{args[0]}"

    import worker.tasks.health as ht

    ht_TaskQueue = ht.TaskQueue
    try:
        ht.TaskQueue = _FakeQueue
        ctx = {
            "session_factory": _factory(session),
            "redis": None,
            "now": NOW,
        }
        await check_accounts_periodic_impl(ctx)
    finally:
        ht.TaskQueue = ht_TaskQueue

    assert stale_at_risk in scheduled
    assert fresh_at_risk not in scheduled
    assert fresh_ok not in scheduled


# --- 6. list_at_risk сортирует по возрастанию score ---------------------------


def test_at_risk_repo_orders_ascending(session):
    _clean(session)
    proxy_id = _make_proxy(session)
    a1 = _make_account(session, proxy_id=proxy_id)
    a2 = _make_account(session, proxy_id=proxy_id)
    a3 = _make_account(session, proxy_id=proxy_id)

    repo = AccountHealthRepository(session)
    for aid, score in [(a1, 80), (a2, 20), (a3, 35)]:
        repo.get_or_create(aid)
        session.execute(
            text("UPDATE account_health SET health_score=:s WHERE account_id=:a"),
            {"s": score, "a": aid},
        )
    session.commit()

    ranked = repo.list_at_risk(max_score=40)
    assert [r.account_id for r in ranked] == [a2, a3]
