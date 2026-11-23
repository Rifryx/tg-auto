"""join_channels: паузы между подписками + остановка при FloodWaitError.

Использует настоящий around_telethon_call (как test_health.py) — FloodWaitError
должен реально записать health-инцидент через него, а не быть проглочен
общим except Exception внутри _run.
"""

from __future__ import annotations


import pytest
from telethon.errors import FloodWaitError

from core.enums import BulkActionType
from core.models import Account
from modules.bulk.actions import ACTION_REGISTRY
from modules.bulk.actions.join_channels import JoinChannelsPayload

pytestmark = pytest.mark.asyncio

_PHONE = iter(range(91_000_000_000, 91_001_000_000))
_TABLES = ("accounts", "health_events", "account_status_history")


class _Req:
    pass


def _clean(session):
    from sqlalchemy import text

    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


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


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


async def _fake_sleep(_seconds):
    return None


class _Client:
    """Фейковый Telethon-клиент: join всегда успешен, если не переопределить."""

    def __init__(self, fail_on: dict[int, Exception] | None = None):
        self.calls: list[str] = []
        self._fail_on = fail_on or {}
        self._i = -1

    async def get_entity(self, ref):
        return ref  # достаточно для JoinChannelRequest-заглушки ниже

    async def __call__(self, req):
        self._i += 1
        self.calls.append(type(req).__name__)
        if self._i in self._fail_on:
            raise self._fail_on[self._i]
        return None


async def test_join_channels_paces_between_refs(session, monkeypatch):
    """Пауза должна быть ПЕРЕД каждым ref'ом, кроме первого — N ref'ов → N-1 сна."""
    _clean(session)
    account_id = _make_account(session)

    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("modules.bulk.actions.join_channels.asyncio.sleep", fake_sleep)

    action = ACTION_REGISTRY[BulkActionType.JOIN_CHANNELS.value]
    client = _Client()
    result = await action.run(
        account_id=account_id,
        payload=JoinChannelsPayload(channel_refs=["@a", "@b", "@c"]),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )

    assert result.ok is True
    assert result.detail["joined"] == ["@a", "@b", "@c"]
    assert len(sleeps) == 2  # перед @b и перед @c, не перед @a
    assert all(s >= 0 for s in sleeps)


async def test_join_channels_stops_on_flood_wait_mid_list(session, monkeypatch):
    """Флудвейт на 2-м ref'е из 4 — остальные 2 в not_attempted, не трогаем их."""
    _clean(session)
    account_id = _make_account(session)
    monkeypatch.setattr("modules.bulk.actions.join_channels.asyncio.sleep", _fake_sleep)

    action = ACTION_REGISTRY[BulkActionType.JOIN_CHANNELS.value]
    client = _Client(fail_on={1: FloodWaitError(request=_Req(), capture=60)})
    result = await action.run(
        account_id=account_id,
        payload=JoinChannelsPayload(channel_refs=["@a", "@b", "@c", "@d"]),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )

    assert result.ok is True  # @a успел зайти до флуда
    assert result.detail["joined"] == ["@a"]
    assert "@b" in result.detail["errors"]
    assert result.detail["not_attempted"] == ["@c", "@d"]
    assert result.detail["stopped_reason"] == "flood_wait"
    # Ни @c, ни @d не должны были вызваться вообще.
    assert client.calls.count("JoinChannelRequest") == 2  # @a (ok) + @b (flood)


async def test_join_channels_flood_wait_on_first_ref_sets_reason(session, monkeypatch):
    """Флудвейт сразу на первом ref'е → ok=False с понятной причиной, не generic."""
    _clean(session)
    account_id = _make_account(session)
    monkeypatch.setattr("modules.bulk.actions.join_channels.asyncio.sleep", _fake_sleep)

    action = ACTION_REGISTRY[BulkActionType.JOIN_CHANNELS.value]
    client = _Client(fail_on={0: FloodWaitError(request=_Req(), capture=120)})
    result = await action.run(
        account_id=account_id,
        payload=JoinChannelsPayload(channel_refs=["@a", "@b"]),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )

    assert result.ok is False
    assert result.detail["joined"] == []
    assert result.detail["not_attempted"] == ["@b"]
    assert result.detail["reason"] == "flood_wait"
    assert result.detail["error"] is not None

