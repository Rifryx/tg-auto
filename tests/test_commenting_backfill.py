"""Backfill истории канала (E2.1): фильтр по keywords/probability,
дедуп с CommentLog, батчи с паузами, порог MAX_POSTS, триггеры из
resolve_channel / sync_account_subscriptions / PATCH post_scope."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from core.enums import CommentStatus
from core.queue.task_names import TaskName
from modules.commenting.repositories import (
    CampaignRepository,
    CommentLogRepository,
    MonitoredChannelRepository,
)
from modules.commenting.schemas import CommentLogCreate
from modules.commenting.worker import backfill, channels
from tests.test_commenting_channels import (
    _ctx,
    _make_account,
    _make_campaign,
    _SpyPublisher,
    _SpyTaskQueue,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
_TABLES = (
    "accounts",
    "health_events",
    "account_status_history",
    '"commenting".campaigns',
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
    '"commenting".monitored_channels',
    '"commenting".campaign_channels',
    '"commenting".channel_blacklist',
    '"commenting".channel_alerts',
)


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _set(session, campaign_id, **fields):
    c = CampaignRepository(session).get(campaign_id)
    for k, v in fields.items():
        setattr(c, k, v)
    session.commit()


def _working_row(session, account_id, campaign_id, tg_id=777):
    repo = MonitoredChannelRepository(session)
    row = repo.create(account_id, f"tg:{tg_id}", is_folder=False)
    row.source_campaign_id = campaign_id
    repo.mark_working(row.id, channel_ref="durov", channel_tg_id=tg_id, title="Chan",
                      discussion_group_id=555, subscribed=True)
    session.commit()
    return row.id


class _HistoryClient:
    """Отвечает списками постов на iter_messages по offset_id.

    Всё, что новее offset_id=0 (или offset_id > этого поста), считается «свежее»
    и отдаётся батчами по batch_size, начиная с самого нового.
    """

    def __init__(self, posts):
        # posts: список (id, text, date) — от новых к старым.
        self.posts = list(posts)
        self.entity = SimpleNamespace(id=777, username="durov", title="Chan")
        self.iter_calls: list[tuple[int, int]] = []

    async def get_entity(self, ref):
        return self.entity

    async def __call__(self, request):
        # backfill не зовёт RPC, но around_telethon_call ждёт корутину.
        return None

    def iter_messages(self, entity, *, limit, offset_id=0):
        self.iter_calls.append((offset_id, limit))
        pool = [p for p in self.posts if offset_id == 0 or p[0] < offset_id]
        page = pool[:limit]

        async def gen():
            for pid, ptext, pdate in page:
                yield SimpleNamespace(id=pid, message=ptext, date=pdate)

        return gen()


def _mk_ctx(session, client, *, task_queue=None, sleep=None, rng=None):
    ctx = _ctx(session, client=client, task_queue=task_queue or _SpyTaskQueue())
    ctx["now"] = NOW
    ctx["sleep"] = sleep or AsyncMock()
    if rng is not None:
        ctx["rng"] = rng
    return ctx


# ── базовый ход по истории ─────────────────────────────────────────────────


async def test_backfill_schedules_for_matching_posts(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, post_scope="existing")
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    row_id = _working_row(session, account_id, campaign_id)

    posts = [
        (100, "релевантный пост", NOW - timedelta(minutes=5)),
        (99, "тоже подходит", NOW - timedelta(minutes=10)),
    ]
    client = _HistoryClient(posts)
    spy = _SpyTaskQueue()
    n = await backfill.backfill_channel(_mk_ctx(session, client, task_queue=spy), account_id, row_id)

    assert n == 2
    assert [e[0] for e in spy.enqueued] == [TaskName.COMMENTING_ON_CHANNEL_POST] * 2
    # Дата поста едет дальше — окно after_post_sec посчитается от неё.
    assert all(e[2]["post_date_ts"] is not None for e in spy.enqueued)
    # После полного вычитывания второй итерации быть не должно — постов больше нет.
    assert len(client.iter_calls) == 1


async def test_backfill_skip_when_scope_is_new(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, post_scope="new")
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    row_id = _working_row(session, account_id, campaign_id)
    client = _HistoryClient([(1, "x", NOW)])
    assert await backfill.backfill_channel(_mk_ctx(session, client), account_id, row_id) == 0


async def test_backfill_deduplicates_with_comment_log(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, post_scope="existing")
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    row_id = _working_row(session, account_id, campaign_id)
    # Пост 100 уже прокомментирован этим аккаунтом (posted).
    CommentLogRepository(session).create(
        CommentLogCreate(
            campaign_id=campaign_id, account_id=account_id, post_channel_msg_id=100,
            comment_text="old", status=CommentStatus.POSTED, posted_message_id=1,
        )
    )
    session.commit()
    posts = [(101, "новый", NOW), (100, "старый", NOW - timedelta(minutes=1))]

    spy = _SpyTaskQueue()
    n = await backfill.backfill_channel(_mk_ctx(session, _HistoryClient(posts), task_queue=spy), account_id, row_id)
    assert n == 1
    assert spy.enqueued[0][1][2] == 101  # только 101 запланирован


async def test_backfill_applies_keywords_filter(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(
        session, campaign_id, post_scope="existing",
        post_selection_mode="keywords", keywords=["крипта"],
    )
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    row_id = _working_row(session, account_id, campaign_id)
    posts = [(3, "новости про крипта", NOW), (2, "рецепт супа", NOW), (1, "без слова", NOW)]

    spy = _SpyTaskQueue()
    n = await backfill.backfill_channel(_mk_ctx(session, _HistoryClient(posts), task_queue=spy), account_id, row_id)
    assert n == 1
    assert spy.enqueued[0][1][2] == 3


# ── батчи и лимиты ──────────────────────────────────────────────────────────


async def test_backfill_pages_through_history_and_hits_max_posts(session, monkeypatch):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, post_scope="existing")
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    row_id = _working_row(session, account_id, campaign_id)
    # BATCH_SIZE=100, MAX=200. Дадим 300 постов, ожидаем 2 батча по 100.
    posts = [(1000 - i, f"post {i}", NOW - timedelta(minutes=i)) for i in range(300)]
    client = _HistoryClient(posts)
    sleep = AsyncMock()
    spy = _SpyTaskQueue()
    n = await backfill.backfill_channel(
        _mk_ctx(session, client, task_queue=spy, sleep=sleep), account_id, row_id
    )
    assert n == 200
    # Между батчами — одна пауза (перед вторым батчем).
    assert sleep.await_count == 1
    # Два вызова iter_messages: первый offset_id=0, второй — с id самого старого из первой пачки.
    assert len(client.iter_calls) == 2
    assert client.iter_calls[0][0] == 0
    assert client.iter_calls[1][0] == 1000 - 99  # min id первой сотни


async def test_backfill_stops_when_channel_not_working(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, post_scope="existing")
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    row_id = _working_row(session, account_id, campaign_id)
    MonitoredChannelRepository(session).mark_failed(row_id, "boom")
    session.commit()
    assert await backfill.backfill_channel(_mk_ctx(session, _HistoryClient([(1, "x", NOW)])), account_id, row_id) == 0


# ── триггер из resolve_channel ─────────────────────────────────────────────


class _ResolveClient:
    def __init__(self, *, channel_id=777, linked=555, left=False):
        self.entity = SimpleNamespace(id=channel_id, username="durov", title="Chan", left=left)
        self._linked = linked
        self.calls: list[str] = []

    async def get_entity(self, ref):
        return self.entity

    async def __call__(self, request):
        name = type(request).__name__
        self.calls.append(name)
        if name == "GetFullChannelRequest":
            return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=self._linked))
        return None


async def test_resolve_schedules_backfill_for_existing_campaign(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, post_scope="mixed", on_not_subscribed_action="subscribe_and_notify")
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    repo = MonitoredChannelRepository(session)
    ch = repo.create(account_id, "@durov", is_folder=False)
    ch.source_campaign_id = campaign_id
    session.commit()
    spy = _SpyTaskQueue()
    ctx = _ctx(session, client=_ResolveClient(), task_queue=spy, publisher=_SpyPublisher())
    assert await channels.resolve_channel(ctx, ch.id) == "working"
    assert any(e[0] == TaskName.COMMENTING_BACKFILL_CHANNEL for e in spy.enqueued)


async def test_resolve_does_not_schedule_backfill_for_new(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, on_not_subscribed_action="subscribe_and_notify")  # scope='new' по умолчанию
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    repo = MonitoredChannelRepository(session)
    ch = repo.create(account_id, "@durov", is_folder=False)
    ch.source_campaign_id = campaign_id
    session.commit()
    spy = _SpyTaskQueue()
    ctx = _ctx(session, client=_ResolveClient(), task_queue=spy, publisher=_SpyPublisher())
    await channels.resolve_channel(ctx, ch.id)
    assert not any(e[0] == TaskName.COMMENTING_BACKFILL_CHANNEL for e in spy.enqueued)


# ── триггер из sync_account_subscriptions ───────────────────────────────────


async def test_subscriptions_scheduler_triggers_backfill(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, post_scope="existing", channel_source_mode="by_account_subscriptions")
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)

    dialogs = [SimpleNamespace(entity=SimpleNamespace(id=1, username="c1", title="C1", broadcast=True, left=False))]

    class _SubsClient:
        async def get_dialogs(self, limit=None):
            return dialogs

        async def __call__(self, request):
            return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=900))

    spy = _SpyTaskQueue()
    ctx = _ctx(session, client=_SubsClient(), task_queue=spy, publisher=_SpyPublisher())
    ctx["sleep"] = AsyncMock()
    assert await channels.sync_account_subscriptions(ctx, account_id, campaign_id) == 1
    assert any(e[0] == TaskName.COMMENTING_BACKFILL_CHANNEL for e in spy.enqueued)


# ── триггер через PATCH кампании ───────────────────────────────────────────


async def test_patch_post_scope_backfills_all_working_channels(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    a1 = _make_account(session, status="assigned", campaign_id=campaign_id)
    a2 = _make_account(session, status="assigned", campaign_id=campaign_id)
    r1 = _working_row(session, a1, campaign_id, tg_id=100)
    r2 = _working_row(session, a2, campaign_id, tg_id=200)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.deps.auth import require_user
    from api.deps.db import get_session
    from api.deps.queue import get_publisher, get_task_queue
    from modules.commenting.api import router

    spy = _SpyTaskQueue()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_publisher] = lambda: None
    app.dependency_overrides[get_task_queue] = lambda: spy
    app.dependency_overrides[require_user] = lambda: "u"
    client = TestClient(app)
    r = client.patch(f"/modules/commenting/campaigns/{campaign_id}", json={"post_scope": "existing"})
    assert r.status_code == 200

    backfills = [e for e in spy.enqueued if e[0] == TaskName.COMMENTING_BACKFILL_CHANNEL]
    assert sorted([(args[0], args[1]) for _, args, _ in backfills]) == sorted([(a1, r1), (a2, r2)])
