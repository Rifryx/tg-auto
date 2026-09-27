"""Промпт 3.1: parse_chat_messages.

Mock TelegramClient: `get_entity` возвращает фейк, `iter_messages` — async
итератор из тестового потока. Проверяем:
* агрегация по sender_id и порог min_messages;
* остановка по days_window (сообщения глубже окна не влияют);
* никаких текстов не сохраняется — только идентификаторы;
* результат пишется как один TargetSource + N Target'ов;
* governor вызывается ровно один раз с action_type="priming_parser".
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("telethon")
pytest.importorskip("structlog")

from core.models import Account
from modules.priming.parser.chat_messages import (
    PARSER_ACTION_TYPE,
    parse_chat_messages,
)
from modules.priming.repositories import (
    CampaignRepository,
    CampaignTargetRepository,
    TargetSourceRepository,
)
from modules.priming.schemas.enums import (
    ParserSourceKind,
    TargetStatus,
    TriggerAction,
)


pytestmark = pytest.mark.asyncio


_PHONE = itertools.count(99_000_000_000)


def _make_account(session) -> Account:
    a = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="pool",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(a)
    session.flush()
    session.commit()
    return a


def _make_campaign(session) -> int:
    c = CampaignRepository(session).create({
        "name": "c",
        "trigger_action": TriggerAction.SECRET_CHAT_REQUEST.value,
    })
    session.commit()
    return c.id


def _factory(session):
    class _Ctx:
        def __enter__(self_inner): return session
        def __exit__(self_inner, *_): return False
    return lambda: _Ctx()


def _msg(dt: datetime, sender_id: int, *, sender_meta: dict | None = None):
    """Собирает объект-сообщение под форму, которую читает парсер."""
    sender = SimpleNamespace(**(sender_meta or {}))
    return SimpleNamespace(date=dt, sender_id=sender_id, sender=sender)


def _client_with_messages(messages):
    """Собирает mock TelegramClient c async-итератором iter_messages."""
    async def _iter(_entity, **_kwargs):
        for m in messages:
            yield m
    client = MagicMock(name="TelegramClient")
    client.get_entity = AsyncMock(return_value=SimpleNamespace(id=-100))
    client.iter_messages = _iter
    return client


def _pool_for(client):
    return SimpleNamespace(
        get=AsyncMock(return_value=client),
        release=AsyncMock(),
    )


# ---------------------------------------------------------------------------


async def test_aggregates_by_sender_and_applies_min_messages(session) -> None:
    campaign_id = _make_campaign(session)
    collector = _make_account(session)

    now = datetime.now(timezone.utc)
    messages = [
        # user 111 — 3 сообщения → пройдёт при min=2 и min=3
        _msg(now - timedelta(hours=1), 111, sender_meta={"username": "alice"}),
        _msg(now - timedelta(hours=2), 111),
        _msg(now - timedelta(hours=3), 111),
        # user 222 — 1 сообщение → отсеется при min>=2
        _msg(now - timedelta(hours=4), 222, sender_meta={"username": "bob"}),
        # user 333 — 2 сообщения → пройдёт при min=2, отсеется при min=3
        _msg(now - timedelta(hours=5), 333),
        _msg(now - timedelta(hours=6), 333),
    ]
    client = _client_with_messages(messages)
    ctx = {
        "session_factory": _factory(session),
        "client_pool": _pool_for(client),
        "governor": SimpleNamespace(check_and_reserve=AsyncMock(return_value=True)),
        "now": now,
    }

    result = await parse_chat_messages(
        ctx,
        campaign_id=campaign_id,
        collector_account_id=collector.id,
        chat_ref="@ainews",
        days_window=7,
        min_messages=2,
    )
    assert result is not None
    assert result.raw_count == 3  # уникальных отправителей всего
    assert result.inserted == 2   # прошли порог: 111, 333

    targets = CampaignTargetRepository(session).list_by_campaign(campaign_id)
    assert {t.tg_user_id for t in targets} == {111, 333}
    for t in targets:
        assert t.status == TargetStatus.PENDING.value
    # username подтянут с первого попавшегося сообщения этого отправителя.
    alice = next(t for t in targets if t.tg_user_id == 111)
    assert alice.username == "alice"


async def test_stops_at_days_window_boundary(session) -> None:
    campaign_id = _make_campaign(session)
    collector = _make_account(session)

    now = datetime.now(timezone.utc)
    messages = [
        _msg(now - timedelta(hours=1), 100),
        _msg(now - timedelta(hours=2), 100),
        # За пределами окна — цикл должен остановиться и НЕ считать 999.
        _msg(now - timedelta(days=10), 999),
        _msg(now - timedelta(days=11), 999),
    ]
    client = _client_with_messages(messages)
    ctx = {
        "session_factory": _factory(session),
        "client_pool": _pool_for(client),
        "governor": SimpleNamespace(check_and_reserve=AsyncMock(return_value=True)),
        "now": now,
    }

    result = await parse_chat_messages(
        ctx, campaign_id=campaign_id, collector_account_id=collector.id,
        chat_ref="@ainews", days_window=7, min_messages=1,
    )
    assert result.raw_count == 1
    assert result.inserted == 1
    targets = CampaignTargetRepository(session).list_by_campaign(campaign_id)
    assert [t.tg_user_id for t in targets] == [100]


async def test_writes_target_source_row(session) -> None:
    campaign_id = _make_campaign(session)
    collector = _make_account(session)
    now = datetime.now(timezone.utc)
    client = _client_with_messages([_msg(now, 42)])
    ctx = {
        "session_factory": _factory(session),
        "client_pool": _pool_for(client),
        "governor": SimpleNamespace(check_and_reserve=AsyncMock(return_value=True)),
        "now": now,
    }

    result = await parse_chat_messages(
        ctx, campaign_id=campaign_id, collector_account_id=collector.id,
        chat_ref="@ainews", days_window=3, min_messages=1,
    )
    source = TargetSourceRepository(session).get_by_id(result.source_id)
    assert source.kind == ParserSourceKind.CHAT_MESSAGES.value
    assert source.chat_ref == "@ainews"
    assert source.raw_count == 1
    assert source.after_filters_count == 1
    assert source.parsed_at is not None


async def test_no_op_when_governor_rejects(session) -> None:
    campaign_id = _make_campaign(session)
    collector = _make_account(session)
    client = _client_with_messages([])
    pool = _pool_for(client)
    governor = SimpleNamespace(check_and_reserve=AsyncMock(return_value=False))
    ctx = {
        "session_factory": _factory(session),
        "client_pool": pool,
        "governor": governor,
        "now": datetime.now(timezone.utc),
    }

    result = await parse_chat_messages(
        ctx, campaign_id=campaign_id, collector_account_id=collector.id,
        chat_ref="@x", days_window=7, min_messages=1,
    )
    assert result is None
    # Ни клиента, ни source-записи.
    pool.get.assert_not_awaited()
    assert TargetSourceRepository(session).list_by_campaign(campaign_id) == []
    # Governor вызывался с типом "priming_parser".
    governor.check_and_reserve.assert_awaited_once_with(
        collector.id, PARSER_ACTION_TYPE,
    )
