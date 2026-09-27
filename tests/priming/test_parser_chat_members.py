"""Промпт 3.2: parse_chat_members + фильтры под postgres_test."""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("telethon")
pytest.importorskip("structlog")

from core.models import Account
from modules.priming.parser.chat_members import parse_chat_members
from modules.priming.parser.filters import FilterOptions
from modules.priming.repositories import (
    BlacklistRepository,
    CampaignRepository,
    CampaignTargetRepository,
    TargetSourceRepository,
)
from modules.priming.schemas.enums import (
    BlacklistReason,
    ParserSourceKind,
    TargetLastSeen,
    TriggerAction,
)


pytestmark = pytest.mark.asyncio


_PHONE = itertools.count(90_100_000_000)


def _acc(session) -> Account:
    a = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="pool",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(a); session.flush(); session.commit()
    return a


def _campaign(session) -> int:
    c = CampaignRepository(session).create({
        "name": "c",
        "trigger_action": TriggerAction.SECRET_CHAT_REQUEST.value,
        "created_by": 42,
    })
    session.commit()
    return c.id


def _factory(session):
    class _Ctx:
        def __enter__(self_inner): return session
        def __exit__(self_inner, *_): return False
    return lambda: _Ctx()


def _user(**over):
    """Собирает SimpleNamespace, соответствующий Telethon User."""
    base = dict(
        id=100, username="alice", phone=None, premium=True,
        bot=False, deleted=False, is_admin=False, status=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _client_with_users(users):
    async def _iter(_entity, **_kw):
        for u in users:
            yield u
    client = MagicMock(name="TelegramClient")
    client.get_entity = AsyncMock(return_value=SimpleNamespace(id=-1))
    client.iter_participants = _iter
    return client


def _pool_for(client):
    return SimpleNamespace(
        get=AsyncMock(return_value=client),
        release=AsyncMock(),
    )


def _ctx(session, client):
    return {
        "session_factory": _factory(session),
        "client_pool": _pool_for(client),
        "governor": SimpleNamespace(check_and_reserve=AsyncMock(return_value=True)),
    }


# ---------------------------------------------------------------------------


async def test_filters_applied_and_breakdown_recorded(session) -> None:
    cid = _campaign(session)
    collector = _acc(session)

    # 1 OK, 1 bot, 1 без username → require_username, 1 blacklisted
    BlacklistRepository(session).create({
        "owner_user_id": 42, "tg_user_id": 44,
        "reason": BlacklistReason.MANUAL.value,
    })
    session.commit()

    users = [
        _user(id=1, username="alice", status=SimpleNamespace()),  # UNKNOWN → not recently
        _user(
            id=2, username="bob",
            status=type("UserStatusRecently", (), {})(),  # маппится на RECENTLY
        ),
        _user(
            id=3, username="", bot=True,
            status=type("UserStatusRecently", (), {})(),
        ),  # bot
        _user(
            id=4, username=None,
            status=type("UserStatusRecently", (), {})(),
        ),  # no_username
        _user(
            id=44, username="shady",
            status=type("UserStatusRecently", (), {})(),
        ),  # blacklisted
    ]
    ctx = _ctx(session, _client_with_users(users))
    result = await parse_chat_members(
        ctx,
        campaign_id=cid,
        collector_account_id=collector.id,
        chat_ref="@members",
        only_recently_seen=True,
        filter_options=FilterOptions(
            require_username=True,
            exclude_bots=True,
            check_blacklist=True,
            owner_user_id=42,
        ),
    )

    # last_seen выпилил user id=1 ДО фильтров (raw_count тоже без него).
    assert result.raw_count == 4
    assert result.inserted == 1  # только bob прошёл

    breakdown = result.filters_breakdown
    assert breakdown.get("bot") == 1
    assert breakdown.get("no_username") == 1
    assert breakdown.get("blacklisted") == 1

    targets = CampaignTargetRepository(session).list_by_campaign(cid)
    assert [t.tg_user_id for t in targets] == [2]
    assert targets[0].username == "bob"
    assert targets[0].last_seen_bucket == TargetLastSeen.RECENTLY.value

    source = TargetSourceRepository(session).get_by_id(result.source_id)
    assert source.kind == ParserSourceKind.CHAT_MEMBERS.value
    assert source.after_filters_count == 1
    assert source.filters_breakdown == breakdown


async def test_only_recently_seen_toggle(session) -> None:
    cid = _campaign(session)
    collector = _acc(session)

    users = [
        _user(id=1, status=type("UserStatusLastMonth", (), {})()),
        _user(id=2, status=type("UserStatusRecently", (), {})()),
    ]
    ctx = _ctx(session, _client_with_users(users))
    result = await parse_chat_members(
        ctx,
        campaign_id=cid,
        collector_account_id=collector.id,
        chat_ref="@x",
        only_recently_seen=False,  # берём всех
        filter_options=FilterOptions(
            require_username=False, exclude_bots=False,
            check_blacklist=False, exclude_deleted=False,
            exclude_admins=False, premium_only=False,
        ),
    )
    assert result.raw_count == 2
    assert result.inserted == 2
