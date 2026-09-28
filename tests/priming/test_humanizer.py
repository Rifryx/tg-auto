"""Промпт 5.1: humanizer_beat — фоновая имитация в паузах между праймами."""

from __future__ import annotations

import itertools
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("telethon")
pytest.importorskip("structlog")

from core.models import Account
from modules.priming.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
)
from modules.priming.schemas.enums import (
    HumanizerMode,
    PrimingAccountState,
    TriggerAction,
)
from modules.priming.worker.humanizer import humanizer_beat


pytestmark = pytest.mark.asyncio


_PHONE = itertools.count(90_400_000_000)


def _acc(session) -> Account:
    a = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="pool",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(a); session.flush(); session.commit()
    return a


def _campaign(session, *, mode: HumanizerMode) -> int:
    c = CampaignRepository(session).create({
        "name": "c",
        "trigger_action": TriggerAction.SECRET_CHAT_REQUEST.value,
        "humanizer_mode": mode.value,
    })
    session.commit()
    return c.id


def _factory(session):
    class _Ctx:
        def __enter__(self_inner): return session
        def __exit__(self_inner, *_): return False
    return lambda: _Ctx()


def _fake_client_and_pool():
    client = MagicMock(name="TelegramClient")
    # Все Telethon-вызовы, к которым обращается humanizer, — awaitable.
    client.get_messages = AsyncMock(return_value=[SimpleNamespace(id=1)])
    client.send_read_acknowledge = AsyncMock()

    async def _call(*_a, **_kw):
        return None
    client.side_effect = _call

    pool = SimpleNamespace(
        get=AsyncMock(return_value=client),
        release=AsyncMock(),
    )
    return client, pool


def _ctx(session, pool, *, allow_reserve: bool = True):
    return {
        "session_factory": _factory(session),
        "client_pool": pool,
        "governor": SimpleNamespace(
            check_and_reserve=AsyncMock(return_value=allow_reserve),
        ),
        "rng": random.Random(0),
        "publisher": None,
    }


# ---------------------------------------------------------------------------


async def test_off_mode_is_noop(session) -> None:
    cid = _campaign(session, mode=HumanizerMode.OFF)
    acc = _acc(session)
    ca = CampaignAccountRepository(session).create({
        "campaign_id": cid, "account_id": acc.id,
    })
    session.commit()
    _, pool = _fake_client_and_pool()
    ctx = _ctx(session, pool)

    result = await humanizer_beat(ctx, cid, ca.id)
    assert result is None
    pool.get.assert_not_awaited()


async def test_non_idle_account_skipped(session) -> None:
    cid = _campaign(session, mode=HumanizerMode.BALANCED)
    acc = _acc(session)
    ca_repo = CampaignAccountRepository(session)
    ca = ca_repo.create({"campaign_id": cid, "account_id": acc.id})
    ca_repo.update(ca.id, {"state": PrimingAccountState.WORKING.value})
    session.commit()
    _, pool = _fake_client_and_pool()
    ctx = _ctx(session, pool)

    result = await humanizer_beat(ctx, cid, ca.id)
    assert result is None
    pool.get.assert_not_awaited()


async def test_balanced_reads_1_to_3_channels(session) -> None:
    cid = _campaign(session, mode=HumanizerMode.BALANCED)
    acc = _acc(session)
    ca = CampaignAccountRepository(session).create({
        "campaign_id": cid, "account_id": acc.id,
    })
    session.commit()
    client, pool = _fake_client_and_pool()
    ctx = _ctx(session, pool)

    result = await humanizer_beat(ctx, cid, ca.id)
    assert result is not None
    executed = result["executed"]
    assert 1 <= len(executed) <= 3
    for entry in executed:
        assert entry.startswith("read:")
    # Мы прочитали хотя бы один канал → get_messages + send_read_acknowledge
    # вызваны хотя бы один раз.
    client.get_messages.assert_awaited()
    client.send_read_acknowledge.assert_awaited()
    pool.release.assert_awaited_once_with(acc.id)


async def test_aggressive_adds_reaction(session) -> None:
    cid = _campaign(session, mode=HumanizerMode.AGGRESSIVE)
    acc = _acc(session)
    ca = CampaignAccountRepository(session).create({
        "campaign_id": cid, "account_id": acc.id,
    })
    session.commit()
    client, pool = _fake_client_and_pool()
    ctx = _ctx(session, pool)

    result = await humanizer_beat(ctx, cid, ca.id)
    assert result is not None
    kinds = {e.split(":")[0] for e in result["executed"]}
    assert "read" in kinds
    assert "react" in kinds


async def test_governor_rejection_skips(session) -> None:
    cid = _campaign(session, mode=HumanizerMode.BALANCED)
    acc = _acc(session)
    ca = CampaignAccountRepository(session).create({
        "campaign_id": cid, "account_id": acc.id,
    })
    session.commit()
    _, pool = _fake_client_and_pool()
    ctx = _ctx(session, pool, allow_reserve=False)

    result = await humanizer_beat(ctx, cid, ca.id)
    assert result is None
    pool.get.assert_not_awaited()
