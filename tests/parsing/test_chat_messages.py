"""Промпт 3.2b: parse_chat_messages пишет в parsing.lists/list_targets."""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("telethon")
pytest.importorskip("structlog")

from core.models import Account
from modules.parsing.parser.chat_messages import parse_chat_messages
from modules.parsing.repositories import (
    ParsedListRepository,
    ParsedListTargetRepository,
)
from modules.priming.schemas.enums import ParserSourceKind


pytestmark = pytest.mark.asyncio


_PHONE = itertools.count(90_200_000_000)


def _acc(session) -> Account:
    a = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="pool",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(a); session.flush(); session.commit()
    return a


def _factory(session):
    class _Ctx:
        def __enter__(self_inner): return session
        def __exit__(self_inner, *_): return False
    return lambda: _Ctx()


def _msg(dt, sender_id, sender_meta=None):
    return SimpleNamespace(
        date=dt, sender_id=sender_id,
        sender=SimpleNamespace(**(sender_meta or {})),
    )


def _client(messages):
    async def _iter(_e, **_kw):
        for m in messages:
            yield m
    c = MagicMock(name="TelegramClient")
    c.get_entity = AsyncMock(return_value=SimpleNamespace(id=-1))
    c.iter_messages = _iter
    return c


async def test_writes_to_parsing_schema(session) -> None:
    collector = _acc(session)
    now = datetime.now(timezone.utc)
    messages = [
        _msg(now - timedelta(hours=1), 111, {"username": "alice"}),
        _msg(now - timedelta(hours=2), 111),
        _msg(now - timedelta(hours=3), 222, {"username": "bob"}),
    ]
    client = _client(messages)
    ctx = {
        "session_factory": _factory(session),
        "client_pool": SimpleNamespace(get=AsyncMock(return_value=client),
                                       release=AsyncMock()),
        "governor": SimpleNamespace(check_and_reserve=AsyncMock(return_value=True)),
        "now": now,
    }

    result = await parse_chat_messages(
        ctx,
        owner_user_id=42, name="AI news 14d",
        collector_account_id=collector.id,
        chat_ref="@ainews", days_window=7, min_messages=2,
    )
    assert result is not None
    assert result.raw_count == 2   # 111 и 222
    assert result.inserted == 1    # только 111 прошёл порог

    parsed = ParsedListRepository(session).list_by_owner(42)
    assert len(parsed) == 1
    lst = parsed[0]
    assert lst.name == "AI news 14d"
    assert lst.source_kind == ParserSourceKind.CHAT_MESSAGES.value

    targets = ParsedListTargetRepository(session).list_by_list(lst.id)
    assert [t.tg_user_id for t in targets] == [111]


async def test_active_mode_max_targets_counts_qualified(session) -> None:
    """Режим «Активные в чате»: max_targets считается по авторам, прошедшим
    min_messages, а не по сырым уникальным. Иначе был баг «собрано 250,
    добавлено 0» — обрыв на 250 авторах с 1 сообщением, потом все отсеяны."""
    collector = _acc(session)
    now = datetime.now(timezone.utc)
    dt = now - timedelta(hours=1)
    # A,A,B,B,C,C — каждый по 2 сообщения.
    messages = [
        _msg(dt, 111, {"username": "a"}), _msg(dt, 111),
        _msg(dt, 222, {"username": "b"}), _msg(dt, 222),
        _msg(dt, 333, {"username": "c"}), _msg(dt, 333),
    ]
    ctx = {
        "session_factory": _factory(session),
        "client_pool": SimpleNamespace(get=AsyncMock(return_value=_client(messages)),
                                       release=AsyncMock()),
        "governor": SimpleNamespace(check_and_reserve=AsyncMock(return_value=True)),
        "now": now,
    }
    result = await parse_chat_messages(
        ctx, owner_user_id=1, name="active",
        collector_account_id=collector.id, chat_ref="@c",
        days_window=7, min_messages=2, max_targets=2,
    )
    assert result is not None
    # Прошли порог и лимит именно A и B; до C не дошли (обрыв по qualified).
    assert result.inserted == 2
