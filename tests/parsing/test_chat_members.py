"""parse_chat_members: лимит max_targets, вступление в чат, удаление строк."""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("telethon")
pytest.importorskip("structlog")

from core.models import Account
from modules.parsing.parser.chat_members import parse_chat_members
from modules.parsing.repositories import (
    ParsedListRepository,
    ParsedListTargetRepository,
)

pytestmark = pytest.mark.asyncio

_PHONE = itertools.count(90_500_000_000)


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


def _participant(i: int):
    return SimpleNamespace(
        id=1000 + i, username=f"user{i}", phone=None, premium=None,
        bot=False, deleted=False, is_admin=False, verified=False,
        scam=False, fake=False, photo=None, first_name=f"N{i}", last_name=None,
        status=None,
    )


class _FakeClient:
    def __init__(self, participants, *, left=None):
        self._participants = participants
        self._left = left
        self.joined: list = []

    async def get_entity(self, _ref):
        return SimpleNamespace(id=-100123, left=self._left, title="Chat")

    async def __call__(self, req):
        self.joined.append(req)
        return None

    async def iter_participants(self, _entity, aggressive=False):
        self.aggressive = aggressive
        for p in self._participants:
            yield p


def _ctx(session, client):
    return {
        "session_factory": _factory(session),
        "client_pool": SimpleNamespace(
            get=_as_async(client), release=_as_async(None)
        ),
        "governor": SimpleNamespace(check_and_reserve=_as_async(True)),
        "now": datetime.now(timezone.utc),
    }


def _as_async(value):
    async def _f(*_a, **_k):
        return value
    return _f


async def test_max_targets_stops_collection(session):
    collector = _acc(session)
    client = _FakeClient([_participant(i) for i in range(10)])
    result = await parse_chat_members(
        _ctx(session, client),
        owner_user_id=7, name="members",
        collector_account_id=collector.id, chat_ref="@big",
        only_recently_seen=False, max_targets=3,
    )
    assert result is not None
    # Собрали ровно столько, сколько просили (фильтры по умолчанию их не режут).
    assert result.inserted == 3
    assert client.aggressive is True  # обход по буквам включён
    assert len(client.joined) == 1    # вступили в чат (entity.left=None)


async def test_already_member_not_rejoined(session):
    collector = _acc(session)
    client = _FakeClient([_participant(i) for i in range(2)], left=False)
    result = await parse_chat_members(
        _ctx(session, client),
        owner_user_id=7, name="m2",
        collector_account_id=collector.id, chat_ref="@c",
        only_recently_seen=False,
    )
    assert result is not None and result.inserted == 2
    assert client.joined == []  # уже участник → не вступаем повторно


async def test_delete_targets_recount(session):
    collector = _acc(session)
    client = _FakeClient([_participant(i) for i in range(5)])
    result = await parse_chat_members(
        _ctx(session, client),
        owner_user_id=7, name="m3",
        collector_account_id=collector.id, chat_ref="@c",
        only_recently_seen=False,
    )
    assert result is not None and result.inserted == 5

    repo = ParsedListTargetRepository(session)
    rows = repo.list_by_list(result.list_id)
    removed = repo.delete_targets(result.list_id, [rows[0].id, rows[1].id])
    session.commit()
    assert removed == 2
    assert repo.count_by_list(result.list_id) == 3
    # Чужой список/несуществующие id не трогаем.
    assert repo.delete_targets(result.list_id, [999999]) == 0
