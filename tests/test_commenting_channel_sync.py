"""E3.2: синхронизация целевых каналов кампании, политика «не подписан»,
ошибки доступа при отправке, чёрный список, алерты. БД настоящая,
Telethon/ClientPool — фейки."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from telethon.errors import ChannelPrivateError, UserNotParticipantError

from core.models import CampaignAccount
from core.queue.task_names import TaskName
from modules.commenting.repositories import (
    CampaignRepository,
    ChannelBlacklistRepository,
    CommentLogRepository,
    MonitoredChannelRepository,
)
from modules.commenting.schemas import CampaignChannelCreate
from modules.commenting.worker import alerts, channels, runner
from tests.test_commenting_channels import (
    _ctx,
    _make_account,
    _make_campaign,
    _SpyPublisher,
    _SpyTaskQueue,
)

pytestmark = pytest.mark.asyncio

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


def _campaign(session, *, policy="notify_only", mode="explicit_links", links=()):
    cid = _make_campaign(session)
    c = CampaignRepository(session).get(cid)
    c.channel_source_mode = mode
    c.on_not_subscribed_action = policy
    session.commit()
    from modules.commenting.repositories import CampaignChannelRepository

    for raw in links:
        CampaignChannelRepository(session).create(cid, CampaignChannelCreate(raw_input=raw))
    session.commit()
    return cid


def _alerts(session):
    from modules.commenting.models import ChannelAlert

    return [(a.kind, a.channel_ref, a.resolved) for a in session.query(ChannelAlert).order_by(ChannelAlert.id)]


class _Client:
    """get_entity → канал с флагом left; запросы логируются."""

    def __init__(self, *, left: bool, channel_id=777, linked=555):
        self.entity = SimpleNamespace(id=channel_id, username="durov", title="Chan", left=left)
        self.linked = linked
        self.calls: list[str] = []
        self.send_message = AsyncMock(return_value=SimpleNamespace(id=999))

    async def get_entity(self, ref):
        return self.entity

    async def __call__(self, request):
        name = type(request).__name__
        self.calls.append(name)
        if name == "GetFullChannelRequest":
            return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=self.linked))
        return None


# ── синхронизация explicit_links ────────────────────────────────────────────


async def test_sync_creates_rows_per_account_and_link_and_is_idempotent(session):
    _clean(session)
    cid = _campaign(session, links=("@one", "@two"))
    a1 = _make_account(session, status="assigned", campaign_id=cid)
    a2 = _make_account(session, status="assigned", campaign_id=cid)

    spy = _SpyTaskQueue()
    ctx = _ctx(session, client=None, task_queue=spy)
    res = await channels.sync_campaign_channels(ctx, cid)
    assert res == {"removed": 0, "resolve": 4}
    rows = MonitoredChannelRepository(session)
    assert sorted((r.account_id, r.input_ref) for a in (a1, a2) for r in rows.list_by_account(a)) == [
        (a1, "@one"), (a1, "@two"), (a2, "@one"), (a2, "@two"),
    ]
    assert all(r.source_campaign_id == cid for a in (a1, a2) for r in rows.list_by_account(a))
    assert [e[0] for e in spy.enqueued] == [TaskName.COMMENTING_RESOLVE_CHANNEL] * 4

    # повторный вызов ничего не дублирует
    spy2 = _SpyTaskQueue()
    assert await channels.sync_campaign_channels(_ctx(session, client=None, task_queue=spy2), cid) == {
        "removed": 0, "resolve": 0,
    }
    assert spy2.enqueued == []


async def test_sync_removes_rows_of_removed_link_detached_account_and_disabled_campaign(session):
    _clean(session)
    cid = _campaign(session, links=("@one", "@two"))
    a1 = _make_account(session, status="assigned", campaign_id=cid)
    a2 = _make_account(session, status="assigned", campaign_id=cid)
    await channels.sync_campaign_channels(_ctx(session, client=None), cid)
    # ручной канал аккаунта — синхронизация кампании его не трогает
    manual = MonitoredChannelRepository(session).create(a1, "@manual", is_folder=False)
    session.commit()

    # ссылку @two убрали, второй аккаунт отвязан
    from modules.commenting.models import CampaignChannel

    session.query(CampaignChannel).filter(CampaignChannel.raw_input == "@two").delete()
    session.get(CampaignAccount, (cid, a2)) and session.delete(session.get(CampaignAccount, (cid, a2)))
    session.commit()
    res = await channels.sync_campaign_channels(_ctx(session, client=None), cid)
    assert res["removed"] == 3  # a1:@two, a2:@one, a2:@two
    refs = sorted(r.input_ref for r in MonitoredChannelRepository(session).list_by_account(a1))
    assert refs == ["@manual", "@one"]
    assert MonitoredChannelRepository(session).list_by_account(a2) == []

    # кампанию выключили — снимаются все её строки, ручная остаётся
    c = CampaignRepository(session).get(cid)
    c.enabled = False
    session.commit()
    await channels.sync_campaign_channels(_ctx(session, client=None), cid)
    assert [r.id for r in MonitoredChannelRepository(session).list_by_account(a1)] == [manual.id]


async def test_sync_subscriptions_mode_delegates_to_account_task(session):
    _clean(session)
    cid = _campaign(session, mode="by_account_subscriptions")
    a1 = _make_account(session, status="assigned", campaign_id=cid)
    spy = _SpyTaskQueue()
    await channels.sync_campaign_channels(_ctx(session, client=None, task_queue=spy), cid)
    assert spy.enqueued == [(TaskName.COMMENTING_SYNC_ACCOUNT_SUBSCRIPTIONS, (a1, cid), {})]


async def test_account_subscriptions_takes_only_broadcast_with_comments(session):
    _clean(session)
    cid = _campaign(session, mode="by_account_subscriptions")
    a1 = _make_account(session, status="assigned", campaign_id=cid)

    def ch(i, **kw):
        return SimpleNamespace(entity=SimpleNamespace(id=i, username=f"c{i}", title=f"C{i}", **kw))

    dialogs = [
        ch(1, broadcast=True, left=False),            # берём
        ch(2, broadcast=False, left=False),           # группа — нет
        ch(3, broadcast=True, left=True),             # вышел — нет
        ch(4, broadcast=True, left=False),            # без обсуждения — нет
    ]

    class _SubsClient:
        async def get_dialogs(self, limit=None):
            return dialogs

        async def __call__(self, request):
            linked = None if request.channel.id == 4 else 900 + request.channel.id
            return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=linked))

    publisher = _SpyPublisher()
    ctx = _ctx(session, client=_SubsClient(), publisher=publisher)
    ctx["sleep"] = AsyncMock()
    assert await channels.sync_account_subscriptions(ctx, a1, cid) == 1
    rows = MonitoredChannelRepository(session).list_by_account(a1)
    assert [(r.input_ref, r.status, r.discussion_group_id, r.source_campaign_id) for r in rows] == [
        ("@c1", "working", 901, cid)
    ]
    # повторный разбор не дублирует
    assert await channels.sync_account_subscriptions(ctx, a1, cid) == 0


# ── политика «не подписан» при разрешении канала ────────────────────────────


async def _campaign_row(session, policy):
    cid = _campaign(session, policy=policy, links=("@durov",))
    acc = _make_account(session, status="assigned", campaign_id=cid)
    await channels.sync_campaign_channels(_ctx(session, client=None), cid)
    row = MonitoredChannelRepository(session).list_by_account(acc)[0]
    return cid, acc, row.id


async def test_notify_only_does_not_join_and_raises_alert(session):
    _clean(session)
    cid, acc, row_id = await _campaign_row(session, "notify_only")
    client = _Client(left=True)
    publisher = _SpyPublisher()

    res = await channels.resolve_channel(_ctx(session, client=client, publisher=publisher), row_id)
    assert res == "not_subscribed"
    assert "JoinChannelRequest" not in client.calls
    row = MonitoredChannelRepository(session).get(row_id)
    assert (row.status, row.error) == ("failed", "not_subscribed")
    assert _alerts(session) == [("not_subscribed", "@durov", False)]
    assert publisher.published[-1][0] == alerts.ALERTS_CHANNEL


async def test_subscribe_policy_joins_notifies_and_closes_old_alert(session):
    _clean(session)
    cid, acc, row_id = await _campaign_row(session, "subscribe_and_notify")
    # старый открытый алерт «не подписан» по этому каналу
    alerts.raise_alert(session, None, campaign_id=cid, account_id=acc, channel_ref="@durov", kind="not_subscribed")
    client = _Client(left=True)

    res = await channels.resolve_channel(_ctx(session, client=client, publisher=_SpyPublisher()), row_id)
    assert res == "working"
    assert "JoinChannelRequest" in client.calls
    assert _alerts(session) == [("not_subscribed", "@durov", True), ("auto_subscribed", "@durov", False)]


async def test_subscribe_policy_already_member_no_alert(session):
    _clean(session)
    cid, acc, row_id = await _campaign_row(session, "subscribe_and_notify")
    res = await channels.resolve_channel(_ctx(session, client=_Client(left=False)), row_id)
    assert res == "working"
    assert _alerts(session) == []


async def test_alert_dedup_while_open(session):
    _clean(session)
    cid = _campaign(session)
    acc = _make_account(session, status="assigned", campaign_id=cid)
    pub = _SpyPublisher()
    first = alerts.raise_alert(session, pub, campaign_id=cid, account_id=acc, channel_ref="@x", kind="access_lost")
    second = alerts.raise_alert(session, pub, campaign_id=cid, account_id=acc, channel_ref="@x", kind="access_lost")
    assert first is not None and second is None
    assert len(pub.published) == 1


# ── ошибки доступа при отправке ─────────────────────────────────────────────


async def _working_row(session, policy):
    cid, acc, row_id = await _campaign_row(session, policy)
    await channels.resolve_channel(_ctx(session, client=_Client(left=False)), row_id)
    return cid, acc, row_id


async def test_channel_private_blacklists_and_stops_channel(session):
    _clean(session)
    cid, acc, row_id = await _working_row(session, "notify_only")
    client = _Client(left=False)
    client.send_message = AsyncMock(side_effect=ChannelPrivateError(request=None))
    pub = _SpyPublisher()

    res = await runner.post_channel_comment(
        _ctx(session, client=client, publisher=pub), acc, cid, 555, "hi", 100, 100
    )
    assert res is None  # задача не падает — ретраев не будет
    logs = CommentLogRepository(session).list_by_campaign(cid)
    assert [(l.status, l.error) for l in logs] == [("failed", "access:ChannelPrivateError")]
    bl = ChannelBlacklistRepository(session).list_by_campaign(cid)
    assert [(b.chat_id, b.username, b.auto) for b in bl] == [(777, "durov", True)]
    assert MonitoredChannelRepository(session).get(row_id).status == "failed"
    assert ("blacklisted", "@durov", False) in _alerts(session)


async def test_not_participant_with_subscribe_policy_rejoins(session):
    _clean(session)
    cid, acc, row_id = await _working_row(session, "subscribe_and_notify")
    client = _Client(left=False)
    client.send_message = AsyncMock(side_effect=UserNotParticipantError(request=None))
    spy = _SpyTaskQueue()

    await runner.post_channel_comment(
        _ctx(session, client=client, task_queue=spy, publisher=_SpyPublisher()),
        acc, cid, 555, "hi", 100, 100,
    )
    assert MonitoredChannelRepository(session).get(row_id).status == "pending"
    assert (TaskName.COMMENTING_RESOLVE_CHANNEL, (row_id,), {}) in spy.enqueued
    assert ("not_subscribed", "@durov", False) in _alerts(session)


async def test_blacklisted_channel_is_not_planned(session):
    _clean(session)
    cid, acc, row_id = await _working_row(session, "notify_only")
    from modules.commenting.schemas import ChannelBlacklistCreate

    ChannelBlacklistRepository(session).create(cid, ChannelBlacklistCreate(username="durov"))
    session.commit()
    spy = _SpyTaskQueue()
    n = await runner.on_channel_post(_ctx(session, client=_Client(left=False), task_queue=spy), acc, row_id, 100)
    assert n == 0
    assert spy.scheduled == []


# ── API и дашборд ───────────────────────────────────────────────────────────


def _api(session, spy_queue):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.deps.auth import require_user
    from api.deps.db import get_session
    from api.deps.queue import get_publisher, get_task_queue
    from modules.commenting.api import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_publisher] = lambda: None
    app.dependency_overrides[get_task_queue] = lambda: spy_queue
    app.dependency_overrides[require_user] = lambda: "u"
    return TestClient(app)


async def test_api_triggers_sync_and_normalizes_blacklist(session):
    _clean(session)
    cid = _campaign(session)
    spy = _SpyTaskQueue()
    api = _api(session, spy)

    assert api.post(f"/modules/commenting/campaigns/{cid}/channels", json={"raw_inputs": ["@a"]}).status_code == 201
    assert api.patch(f"/modules/commenting/campaigns/{cid}", json={"on_not_subscribed_action": "subscribe_and_notify"}).status_code == 200
    assert api.patch(f"/modules/commenting/campaigns/{cid}", json={"name": "renamed"}).status_code == 200
    syncs = [e for e in spy.enqueued if e[0] == TaskName.COMMENTING_SYNC_CAMPAIGN_CHANNELS]
    assert syncs == [(TaskName.COMMENTING_SYNC_CAMPAIGN_CHANNELS, (cid,), {})] * 2  # переименование — без синка

    r = api.post(f"/modules/commenting/campaigns/{cid}/blacklist", json={"chat_id": -1001234567890})
    assert r.status_code == 201 and r.json()["chat_id"] == 1234567890
    r = api.post(f"/modules/commenting/campaigns/{cid}/blacklist", json={"username": "@Some"})
    assert r.json()["username"] == "Some"


async def test_api_delete_campaign_drops_its_monitoring(session):
    _clean(session)
    cid, acc, row_id = await _working_row(session, "notify_only")
    manual = MonitoredChannelRepository(session).create(acc, "@manual", is_folder=False)
    session.commit()
    api = _api(session, _SpyTaskQueue())
    assert api.delete(f"/modules/commenting/campaigns/{cid}").status_code == 204
    assert [r.id for r in MonitoredChannelRepository(session).list_by_account(acc)] == [manual.id]


async def test_alerts_endpoint_and_resolve(session):
    _clean(session)
    cid = _campaign(session)
    acc = _make_account(session, status="assigned", campaign_id=cid)
    aid = alerts.raise_alert(session, None, campaign_id=cid, account_id=acc, channel_ref="@x", kind="not_subscribed")
    api = _api(session, _SpyTaskQueue())
    got = api.get(f"/modules/commenting/campaigns/{cid}/alerts").json()
    assert [(a["id"], a["kind"]) for a in got] == [(aid, "not_subscribed")]
    assert api.post(f"/modules/commenting/alerts/{aid}/resolve").json()["resolved"] is True
    assert api.get(f"/modules/commenting/campaigns/{cid}/alerts").json() == []


async def test_dashboard_includes_open_channel_alerts(session):
    from api.services.monitoring import _alerts as dashboard_alerts

    _clean(session)
    cid = _campaign(session)
    acc = _make_account(session, status="assigned", campaign_id=cid)
    alerts.raise_alert(session, None, campaign_id=cid, account_id=acc, channel_ref="@x", kind="not_subscribed")
    alerts.raise_alert(session, None, campaign_id=cid, account_id=acc, channel_ref="@y", kind="auto_subscribed")
    items = dashboard_alerts(session, None)
    kinds = [(i["event_type"], i["meta"]["campaign_id"]) for i in items]
    assert kinds == [("commenting.not_subscribed", cid)]  # auto_subscribed на главной не показываем
