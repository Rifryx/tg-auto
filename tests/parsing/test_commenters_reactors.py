"""max_targets и прогресс для channel_commenters / post_reactors."""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("telethon")
pytest.importorskip("structlog")

from core.models import Account
from modules.parsing.parser.channel_commenters import parse_channel_commenters
from modules.parsing.parser.post_reactors import parse_post_reactors

pytestmark = pytest.mark.asyncio

_PHONE = itertools.count(90_700_000_000)


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


def _as_async(value):
    async def _f(*_a, **_k):
        return value
    return _f


def _ctx(session, client):
    return {
        "session_factory": _factory(session),
        "client_pool": SimpleNamespace(get=_as_async(client), release=_as_async(None)),
        "governor": SimpleNamespace(check_and_reserve=_as_async(True)),
        "now": datetime.now(timezone.utc),
    }


def _sender(i: int):
    return SimpleNamespace(
        username=f"u{i}", phone=None, premium=None, bot=False, deleted=False,
        verified=False, scam=False, fake=False, photo=None,
        first_name=f"N{i}", last_name=None,
    )


class _CommClient:
    def __init__(self, messages, linked_id=555):
        self._messages = messages
        self._linked = linked_id

    async def get_entity(self, ref):
        if ref == self._linked:
            return SimpleNamespace(id=self._linked, left=False, title="Disc")
        return SimpleNamespace(id=-100, left=False, title="Chan")

    async def __call__(self, _req):  # GetFullChannelRequest
        return SimpleNamespace(
            full_chat=SimpleNamespace(linked_chat_id=self._linked)
        )

    async def iter_messages(self, _disc):
        for m in self._messages:
            yield m


async def test_commenters_max_targets(session):
    now = datetime.now(timezone.utc)
    msgs = [
        SimpleNamespace(date=now, sender_id=1000 + i, sender=_sender(i))
        for i in range(10)
    ]
    collector = _acc(session)
    result = await parse_channel_commenters(
        _ctx(session, _CommClient(msgs)),
        owner_user_id=1, name="comm",
        collector_account_id=collector.id, chat_ref="@chan",
        days_window=30, min_messages=1, max_targets=3,
    )
    assert result is not None
    assert result.inserted == 3  # остановились на лимите по уникальным авторам


class _ReactClient:
    def __init__(self, n_posts, users_per_post):
        self._posts = [SimpleNamespace(id=i + 1) for i in range(n_posts)]
        self._users_per_post = users_per_post
        self._counter = itertools.count(2000)

    async def get_entity(self, _ref):
        return SimpleNamespace(id=-100, left=False)

    async def get_messages(self, _entity, limit=None):
        return self._posts

    async def __call__(self, _req):  # GetMessageReactionsListRequest
        users = [
            SimpleNamespace(id=next(self._counter), username=None, phone=None,
                            premium=None, bot=False, deleted=False, is_admin=False,
                            verified=False, scam=False, fake=False, photo=None,
                            first_name="R", last_name=None, status=None)
            for _ in range(self._users_per_post)
        ]
        return SimpleNamespace(users=users)


async def test_reactors_max_targets(session):
    collector = _acc(session)
    # 10 постов по 1 реактору; лимит 3 → останавливаемся после 3 постов.
    result = await parse_post_reactors(
        _ctx(session, _ReactClient(n_posts=10, users_per_post=1)),
        owner_user_id=1, name="react",
        collector_account_id=collector.id, chat_ref="@chan",
        posts_limit=10, reactions_per_post=100, min_reactions=1, max_targets=3,
    )
    assert result is not None
    assert result.inserted == 3
