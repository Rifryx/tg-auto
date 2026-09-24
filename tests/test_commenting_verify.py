"""Verify-after-post: планирование, коммент виден / удалён, дедуп повторов,
скип для непригодного аккаунта или без обсуждения (E4.2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from core.enums import CommentStatus
from core.models import CommentLog
from core.queue.task_names import TaskName
from modules.commenting.repositories import (
    CampaignRepository,
    CommentLogRepository,
    MonitoredChannelRepository,
)
from modules.commenting.schemas import CommentLogCreate
from modules.commenting.worker import runner, verify
from tests.test_commenting_channels import (
    _ctx as _base_ctx,
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
)


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _set(session, campaign_id, **fields):
    c = CampaignRepository(session).get(campaign_id)
    for k, v in fields.items():
        setattr(c, k, v)
    session.commit()


def _log(session, campaign_id, account_id, *, posted_message_id=999):
    row = CommentLogRepository(session).create(
        CommentLogCreate(
            campaign_id=campaign_id, account_id=account_id, post_channel_msg_id=100,
            comment_text="hi", status=CommentStatus.POSTED,
            posted_message_id=posted_message_id,
        )
    )
    session.commit()
    return row.id


class _Client:
    def __init__(self, *, exists: bool = True):
        self.exists = exists
        self.get_messages = AsyncMock(
            return_value=[SimpleNamespace(id=999, message="hi")] if exists else [None]
        )


def _ctx(session, client, *, publisher=None):
    return _base_ctx(session, client=client, task_queue=_SpyTaskQueue(), publisher=publisher)


# ── verify_comment: успешно / удалён / повтор ────────────────────────────────


async def test_verify_ok_marks_verified_at_and_publishes(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, verify_after_post=True, discussion_group_id=555)
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    log_id = _log(session, campaign_id, account_id)
    pub = _SpyPublisher()

    result = await verify.verify_comment(
        {**_ctx(session, _Client(exists=True), publisher=pub), "now": NOW}, log_id,
    )
    assert result == "ok"
    row = session.get(CommentLog, log_id)
    assert row.verified_at == NOW and row.removed_at is None
    assert row.status == "posted"
    kinds = [ch for ch, _ in pub.published]
    assert verify.VERIFY_OK_CHANNEL in kinds


async def test_verify_missing_message_flags_and_alerts(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, verify_after_post=True, discussion_group_id=555)
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    log_id = _log(session, campaign_id, account_id)
    pub = _SpyPublisher()

    result = await verify.verify_comment(
        {**_ctx(session, _Client(exists=False), publisher=pub), "now": NOW}, log_id,
    )
    assert result == "removed"
    row = session.get(CommentLog, log_id)
    assert row.status == "flagged" and row.error == "removed_by_moderator"
    assert row.removed_at == NOW
    assert any(
        ch == verify.VERIFY_REMOVED_CHANNEL and p.get("kind") == "comment_removed"
        for ch, p in pub.published
    )


async def test_verify_repeat_is_noop_after_flag(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, verify_after_post=True, discussion_group_id=555)
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    log_id = _log(session, campaign_id, account_id)

    ctx = {**_ctx(session, _Client(exists=False), publisher=_SpyPublisher()), "now": NOW}
    assert await verify.verify_comment(ctx, log_id) == "removed"
    # Второй запуск на том же логе не пересчитывает и не отправляет второй алерт.
    pub2 = _SpyPublisher()
    ctx2 = {**_ctx(session, _Client(exists=True), publisher=pub2), "now": NOW + timedelta(minutes=5)}
    assert await verify.verify_comment(ctx2, log_id) == "skipped"
    assert pub2.published == []


async def test_verify_skips_when_account_not_eligible(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, verify_after_post=True, discussion_group_id=555)
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    log_id = _log(session, campaign_id, account_id)
    # Аккаунт ушёл в cooldown между постом и проверкой.
    from core.models import Account

    session.get(Account, account_id).status = "cooldown"
    session.commit()

    result = await verify.verify_comment(
        {**_ctx(session, _Client(exists=True)), "now": NOW}, log_id,
    )
    assert result == "skipped"
    row = session.get(CommentLog, log_id)
    assert row.verified_at is None and row.removed_at is None


async def test_verify_uses_monitored_channel_group_for_account_centric(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, verify_after_post=True, discussion_group_id=None)
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    row = MonitoredChannelRepository(session).create(
        account_id, "@durov", is_folder=False
    )
    MonitoredChannelRepository(session).mark_working(
        row.id, channel_ref="durov", channel_tg_id=777, title="C", discussion_group_id=999,
    )
    session.commit()
    log_id = _log(session, campaign_id, account_id)
    client = _Client(exists=True)

    result = await verify.verify_comment(
        {**_ctx(session, client), "now": NOW}, log_id,
    )
    assert result == "ok"
    client.get_messages.assert_awaited_once()
    assert client.get_messages.await_args.args[0] == 999


async def test_verify_network_error_is_skipped_not_removed(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, verify_after_post=True, discussion_group_id=555)
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)
    log_id = _log(session, campaign_id, account_id)
    client = _Client(exists=True)
    client.get_messages = AsyncMock(side_effect=RuntimeError("network"))

    result = await verify.verify_comment(
        {**_ctx(session, client), "now": NOW}, log_id,
    )
    assert result == "skipped"
    row = session.get(CommentLog, log_id)
    assert row.status == "posted" and row.verified_at is None and row.removed_at is None


# ── планирование из runner ──────────────────────────────────────────────────


def _factory(session):
    class _CM:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _CM()


async def test_runner_schedules_verify_on_success(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, verify_after_post=True, verify_delay_sec=42, discussion_group_id=555)
    _make_account(session, status="assigned", campaign_id=campaign_id)
    spy = _SpyTaskQueue()
    await runner._schedule_verify(
        {"session_factory": _factory(session), "task_queue": spy},
        campaign_id, comment_log_id=17, posted_message_id=555, now=NOW,
    )
    name, run_at, args, _ = spy.scheduled[0]
    assert name == TaskName.COMMENTING_VERIFY_COMMENT
    assert run_at == NOW + timedelta(seconds=42)
    assert args == (17,)


async def test_runner_does_not_schedule_when_flag_off(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, verify_after_post=False, discussion_group_id=555)
    spy = _SpyTaskQueue()
    await runner._schedule_verify(
        {"session_factory": _factory(session), "task_queue": spy},
        campaign_id, comment_log_id=1, posted_message_id=1, now=NOW,
    )
    assert spy.scheduled == []


async def test_runner_does_not_schedule_without_posted_message(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, verify_after_post=True, discussion_group_id=555)
    spy = _SpyTaskQueue()
    await runner._schedule_verify(
        {"session_factory": _factory(session), "task_queue": spy},
        campaign_id, comment_log_id=1, posted_message_id=None, now=NOW,
    )
    assert spy.scheduled == []


# ── notifier: форматирование comment_removed ────────────────────────────────


def test_notifier_formats_comment_removed():
    from bot.notifier import _fmt_commenting_alert

    result = _fmt_commenting_alert(
        {"kind": "comment_removed", "account_id": 7, "campaign_id": 3, "posted_message_id": 88}
    )
    assert result is not None
    assert "снял коммент" in result.lower()
    # без «Канал: —»
    assert "Канал:" not in result
    assert "#88" in result and "#3" in result
