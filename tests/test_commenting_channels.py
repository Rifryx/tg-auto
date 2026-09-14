"""Тесты аккаунт-центричного мониторинга каналов (resolve/leave/comment).

БД настоящая; Telethon-клиент и ClientPool — фейки; now/rng инъектируются.
Реальная подписка/discussion-группа проверяется на живых аккаунтах (см. Phase 2).
"""

from __future__ import annotations

import itertools
from datetime import datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from core.models import Account, CampaignAccount
from core.queue.task_names import TaskName
from modules.commenting.repositories import (
    CampaignRepository,
    CommentLogRepository,
    MonitoredChannelRepository,
)
from modules.commenting.schemas import CampaignCreate
from modules.commenting.worker import channels, registry, runner

pytestmark = pytest.mark.asyncio

NOW_INSIDE = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
_PHONE = itertools.count(97_000_000_000)
_TABLES = (
    "accounts",
    "health_events",
    "account_status_history",
    '"commenting".campaigns',
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
    '"commenting".monitored_channels',
)


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


class _SpyTaskQueue:
    def __init__(self):
        self.enqueued = []
        self.scheduled = []

    async def enqueue(self, name, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
        return "job"

    async def schedule(self, name, run_at, *args, **kwargs):
        self.scheduled.append((name, run_at, args, kwargs))
        return "job"


class _FakePool:
    def __init__(self, client):
        self._client = client
        self.released = []

    async def get(self, account_id):
        return self._client

    async def release(self, account_id):
        self.released.append(account_id)


class _FakeGovernor:
    def __init__(self, allow=True):
        self.allow = allow

    async def check_and_reserve(self, account_id, action_type):
        return self.allow


class _FakeLLM:
    async def generate(self, system, messages, max_tokens=200, temperature=0.8):
        return "auto-generated comment"


class _SpyPublisher:
    def __init__(self):
        self.published = []

    def publish(self, channel, payload):
        self.published.append((channel, payload))


class _Rng:
    def random(self):
        return 0.9

    def uniform(self, a, b):
        return a


class _ResolveClient:
    """Фейковый Telethon-клиент: get_entity + вызовы request'ов + send_message."""

    def __init__(self, *, channel_id=777, linked=555, username="durov", title="Chan"):
        self._entity = SimpleNamespace(id=channel_id, username=username, title=title)
        self._linked = linked
        self.calls: list[str] = []
        self.send_message = AsyncMock(return_value=SimpleNamespace(id=999))

    async def get_entity(self, ref):
        return self._entity

    async def __call__(self, request):
        name = type(request).__name__
        self.calls.append(name)
        if name == "GetFullChannelRequest":
            return SimpleNamespace(
                full_chat=SimpleNamespace(linked_chat_id=self._linked)
            )
        if name == "ImportChatInviteRequest":
            return SimpleNamespace(chats=[self._entity])
        return None


class _FailingClient:
    async def get_entity(self, ref):
        raise RuntimeError("no such channel")

    async def __call__(self, request):
        raise RuntimeError("no such channel")


def _ctx(session, *, client, task_queue=None, publisher=None, governor=None):
    return {
        "session_factory": _factory(session),
        "now": NOW_INSIDE,
        "rng": _Rng(),
        "task_queue": task_queue or _SpyTaskQueue(),
        "client_pool": _FakePool(client),
        "governor": governor,
        "llm_provider": _FakeLLM(),
        "publisher": publisher,
    }


def _make_account(session, *, status="pool", campaign_id=None) -> int:
    acc = Account(
        phone=f"+{next(_PHONE)}",
        session_enc=b"enc",
        status=status,
        assigned_container_type="commenting" if campaign_id else None,
        assigned_container_id=campaign_id,
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    session.add(acc)
    session.flush()
    if campaign_id is not None:
        session.add(CampaignAccount(campaign_id=campaign_id, account_id=acc.id))
    session.commit()
    return acc.id


def _make_campaign(session) -> int:
    c = CampaignRepository(session).create(
        CampaignCreate(
            name="camp",
            target_channel="@ch",
            base_system_prompt="comment nicely",
            llm_provider="deepseek",
            active_hours_start=time(9, 0),
            active_hours_end=time(23, 0),
            active_hours_tz="UTC",
            posting_delay_min_sec=10,
            posting_delay_max_sec=60,
            discussion_group_id=555,
        )
    )
    session.commit()
    return c.id


# --- resolve_channel: публичный канал → working + discussion-группа -----------


async def test_resolve_public_channel_marks_working(session):
    _clean(session)
    account_id = _make_account(session)
    with session.begin_nested():
        ch = MonitoredChannelRepository(session).create(
            account_id, "https://t.me/durov", is_folder=False
        )
    session.commit()
    channel_id = ch.id

    client = _ResolveClient(channel_id=777, linked=555)
    publisher = _SpyPublisher()
    result = await channels.resolve_channel(
        _ctx(session, client=client, publisher=publisher), channel_id
    )

    assert result == "working"
    row = MonitoredChannelRepository(session).get(channel_id)
    assert row.status == "working"
    assert row.subscribed is True
    assert row.channel_tg_id == 777
    assert row.discussion_group_id == 555
    assert "JoinChannelRequest" in client.calls
    assert "GetFullChannelRequest" in client.calls
    # событие attach опубликовано для реестра слушателей
    assert publisher.published == [
        (channels.CHANNEL_LIFECYCLE_CHANNEL,
         {"account_id": account_id, "channel_id": channel_id, "action": "attach"})
    ]


async def test_resolve_failure_marks_failed(session):
    _clean(session)
    account_id = _make_account(session)
    ch = MonitoredChannelRepository(session).create(
        account_id, "@nope", is_folder=False
    )
    session.commit()

    result = await channels.resolve_channel(
        _ctx(session, client=_FailingClient()), ch.id
    )

    assert result == "failed"
    row = MonitoredChannelRepository(session).get(ch.id)
    assert row.status == "failed"
    assert "no such channel" in row.error


# --- leave_channel -----------------------------------------------------------


async def test_leave_channel_calls_leave(session):
    _clean(session)
    account_id = _make_account(session)
    client = _ResolveClient()

    ok = await channels.leave_channel(
        _ctx(session, client=client), account_id, "@durov", 777
    )

    assert ok is True
    assert "LeaveChannelRequest" in client.calls


# --- on_channel_post → один post_channel_comment для владельца ---------------


async def test_on_channel_post_schedules_one_comment(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    repo = MonitoredChannelRepository(session)
    ch = repo.create(account_id, "@durov", is_folder=False)
    repo.mark_working(
        ch.id, channel_ref="durov", channel_tg_id=777, title="Chan",
        discussion_group_id=555,
    )
    session.commit()

    spy = _SpyTaskQueue()
    ctx = _ctx(session, client=_ResolveClient(), task_queue=spy)
    count = await runner.on_channel_post(ctx, account_id, ch.id, 100)

    assert count == 1
    assert len(spy.scheduled) == 1
    name, _run_at, args, _kwargs = spy.scheduled[0]
    assert name == TaskName.COMMENTING_POST_CHANNEL_COMMENT
    # args: account_id, campaign_id, discussion_group_id, text, channel_msg_id, reply_target
    assert args[0] == account_id
    assert args[1] == campaign_id
    assert args[2] == 555
    assert args[4] == 100


async def test_post_channel_comment_posts_and_logs(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)

    client = _ResolveClient()
    ctx = _ctx(session, client=client, governor=_FakeGovernor(allow=True))
    result = await runner.post_channel_comment(
        ctx, account_id, campaign_id, 555, "hello", 100, 100
    )

    assert result == 999
    client.send_message.assert_awaited_once()
    logs = CommentLogRepository(session).list_by_campaign(campaign_id)
    assert len(logs) == 1
    assert logs[0].status == "posted"
    assert logs[0].account_id == account_id
    assert ctx["client_pool"].released == [account_id]


# --- ChannelListenerRegistry: attach → пост канала → on_channel_post ----------


class _ChannelListenerClient:
    """Клиент с add/remove_event_handler для реестра слушателей каналов."""

    def __init__(self):
        self.added: list = []

    def add_event_handler(self, handler, event):
        self.added.append((handler, event))

    def remove_event_handler(self, handler, event):
        self.added = [(h, e) for h, e in self.added if h is not handler]


async def test_channel_registry_attach_fires_on_channel_post(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    repo = MonitoredChannelRepository(session)
    ch = repo.create(account_id, "@durov", is_folder=False)
    repo.mark_working(
        ch.id, channel_ref="durov", channel_tg_id=777, title="Chan",
        discussion_group_id=555,
    )
    session.commit()

    client = _ChannelListenerClient()
    spy = _SpyTaskQueue()
    ctx = _ctx(session, client=client, task_queue=spy)

    reg = registry.ChannelListenerRegistry()
    # load_all находит working-канал assigned-аккаунта enabled-кампании
    started = await reg.load_all(ctx)
    assert started == [ch.id]
    assert reg.is_attached(ch.id)
    assert len(client.added) == 1
    handler, _event = client.added[0]

    # пост самого канала (sender_id == channel_tg_id) → on_channel_post
    await handler(SimpleNamespace(message=SimpleNamespace(sender_id=777, id=100)))
    # чужой коммент — игнор
    await handler(SimpleNamespace(message=SimpleNamespace(sender_id=42, id=101)))
    assert spy.enqueued == [
        (TaskName.COMMENTING_ON_CHANNEL_POST, (account_id, ch.id, 100), {})
    ]

    # detach снимает handler и возвращает клиента в пул (последний канал)
    assert await reg.detach(ch.id) is True
    assert reg.active() == []
    assert client.added == []
    assert ctx["client_pool"].released == [account_id]


async def test_channel_registry_shares_client_across_channels(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    repo = MonitoredChannelRepository(session)
    ids = []
    for ref, tg in (("@a", 111), ("@b", 222)):
        ch = repo.create(account_id, ref, is_folder=False)
        repo.mark_working(
            ch.id, channel_ref=ref.lstrip("@"), channel_tg_id=tg, title="X",
            discussion_group_id=500 + tg,
        )
        ids.append(ch.id)
    session.commit()

    client = _ChannelListenerClient()
    ctx = _ctx(session, client=client, task_queue=_SpyTaskQueue())
    reg = registry.ChannelListenerRegistry()
    await reg.load_all(ctx)

    assert sorted(reg.active()) == sorted(ids)
    assert len(client.added) == 2  # один клиент, два handler'а

    # снятие первого канала не отпускает клиента (второй ещё активен)
    await reg.detach(ids[0])
    assert ctx["client_pool"].released == []
    # снятие второго — отпускает
    await reg.detach(ids[1])
    assert ctx["client_pool"].released == [account_id]
