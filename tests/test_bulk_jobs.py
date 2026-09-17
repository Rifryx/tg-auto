"""Тесты bulk-заданий (этап 5 УТП).

Полностью на реальной Postgres (session-фикстура). Telethon не используется —
регистрируем тестовое action без клиента и убеждаемся, что:
* dispatch ставит item'ы в очередь и переводит job в RUNNING;
* item выполняет action, обновляет счётчики и публикует прогресс;
* cancel останавливает pending-item'ы;
* retry-failed переоткрывает провалы и re-enqueue'ит dispatch;
* items у banned/retired аккаунтов помечаются skipped.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import text

from core.enums import BulkActionType, BulkItemStatus, BulkJobStatus
from core.models import Account, BulkJob, BulkJobItem
from core.repositories.bulk_job import BulkJobRepository
from modules.bulk.actions.registry import (
    ACTION_REGISTRY,
    BulkAction,
    BulkActionResult,
)
from pydantic import BaseModel, ConfigDict
from worker.tasks.bulk import (
    BULK_PROGRESS_CHANNEL,
    dispatch_impl,
    item_impl,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)

_TABLES = (
    "bulk_job_items",
    "bulk_jobs",
    "accounts",
    "proxies",
    "health_events",
    "account_health",
    "account_status_history",
    "warming_activities",
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
)
_PHONE = iter(range(60_000_000_000, 60_001_000_000))


class _SpyPublisher:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def publish(self, channel, payload):
        self.events.append((channel, dict(payload)))


class _FakeQueue:
    def __init__(self, redis=None):
        self.enqueued: list[tuple[str, tuple]] = []

    async def enqueue(self, name, *args, **kwargs):
        # TaskName принимает str или enum; берём .value если enum.
        n = getattr(name, "value", name)
        self.enqueued.append((n, args))
        return f"job-{n}-{args}"


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


def _make_account(session, *, status="pool") -> int:
    acc = Account(
        phone=f"+{next(_PHONE)}",
        session_enc=b"enc",
        status=status,
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    session.add(acc)
    session.flush()
    session.commit()
    return acc.id


# ── тестовое действие (не трогает Telethon) ───────────────────────────────────
class _NoopPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


_TEST_ACTION_NAME = BulkActionType.SET_PERSONA.value  # переиспользуем разрешённое имя
_calls: list[int] = []


async def _noop_run(*, account_id, payload, **_):
    _calls.append(account_id)
    return BulkActionResult(ok=True, detail={"account_id": account_id})


@pytest.fixture()
def _register_noop_action():
    """Подменяем set_persona тестовым noop-хендлером на время теста."""
    original = ACTION_REGISTRY.get(_TEST_ACTION_NAME)
    ACTION_REGISTRY[_TEST_ACTION_NAME] = BulkAction(
        name=_TEST_ACTION_NAME,
        requires_client=False,
        payload_schema=_NoopPayload,
        run=_noop_run,
    )
    _calls.clear()
    yield
    if original is not None:
        ACTION_REGISTRY[_TEST_ACTION_NAME] = original


# ── 1. dispatch enqueues items and marks job running ─────────────────────────


async def test_dispatch_enqueues_and_marks_running(session, _register_noop_action):
    _clean(session)
    a1 = _make_account(session)
    a2 = _make_account(session)
    repo = BulkJobRepository(session)
    job = repo.create(
        action_type=_TEST_ACTION_NAME,
        payload={},
        initiator="user-1",
        account_ids=[a1, a2],
    )
    session.commit()

    fake_queue = _FakeQueue()

    import worker.tasks.bulk as bt

    original = bt.TaskQueue
    try:
        bt.TaskQueue = lambda redis=None: fake_queue
        result = await dispatch_impl(
            {"session_factory": _factory(session), "now": NOW}, job.id
        )
    finally:
        bt.TaskQueue = original

    assert result["enqueued"] == 2
    session.expire_all()
    updated = repo.get(job.id)
    assert updated.status == BulkJobStatus.RUNNING.value
    assert updated.started_at == NOW
    assert len(fake_queue.enqueued) == 2
    assert all(name == "bulk.item" for name, _ in fake_queue.enqueued)


# ── 2. item runs the action and updates counters ─────────────────────────────


async def test_item_runs_action_and_finalizes_job(session, _register_noop_action):
    _clean(session)
    a1 = _make_account(session)
    repo = BulkJobRepository(session)
    job = repo.create(
        action_type=_TEST_ACTION_NAME,
        payload={},
        initiator="user-1",
        account_ids=[a1],
    )
    session.commit()
    item_id = repo.list_items(job.id)[0].id

    publisher = _SpyPublisher()
    ctx = {
        "session_factory": _factory(session),
        "publisher": publisher,
        "client_pool": None,
        "now": NOW,
    }
    result = await item_impl(ctx, job.id, item_id)
    assert result["status"] == BulkItemStatus.DONE.value

    session.expire_all()
    it = repo.get_item(item_id)
    assert it.status == BulkItemStatus.DONE.value
    assert it.result == {"account_id": a1}

    updated = repo.get(job.id)
    assert updated.done_count == 1
    assert updated.status == BulkJobStatus.DONE.value  # всё закрыто
    assert updated.finished_at is not None

    # pub/sub-события: один item.status=done.
    assert any(
        ch == BULK_PROGRESS_CHANNEL and p["status"] == "done"
        for ch, p in publisher.events
    )
    assert a1 in _calls


# ── 3. banned/retired → skipped, action не вызывается ─────────────────────────


async def test_item_skips_unavailable_account(session, _register_noop_action):
    _clean(session)
    banned = _make_account(session, status="banned")
    repo = BulkJobRepository(session)
    job = repo.create(
        action_type=_TEST_ACTION_NAME,
        payload={},
        initiator="u",
        account_ids=[banned],
    )
    session.commit()
    item_id = repo.list_items(job.id)[0].id

    ctx = {
        "session_factory": _factory(session),
        "publisher": _SpyPublisher(),
        "client_pool": None,
        "now": NOW,
    }
    _calls.clear()
    await item_impl(ctx, job.id, item_id)

    session.expire_all()
    it = repo.get_item(item_id)
    assert it.status == BulkItemStatus.SKIPPED.value
    assert not _calls  # action не звался

    updated = repo.get(job.id)
    assert updated.skipped_count == 1
    assert updated.status == BulkJobStatus.DONE.value  # skipped считается закрытым


# ── 4. exception → failed + job закрывается в FAILED ─────────────────────────


async def test_item_captures_exception_as_failed(session):
    _clean(session)
    a = _make_account(session)

    async def _boom(*, account_id, payload, **_):
        raise RuntimeError("kaboom")

    original = ACTION_REGISTRY.get(_TEST_ACTION_NAME)
    ACTION_REGISTRY[_TEST_ACTION_NAME] = BulkAction(
        name=_TEST_ACTION_NAME,
        requires_client=False,
        payload_schema=_NoopPayload,
        run=_boom,
    )
    try:
        repo = BulkJobRepository(session)
        job = repo.create(
            action_type=_TEST_ACTION_NAME,
            payload={},
            initiator="u",
            account_ids=[a],
        )
        session.commit()
        item_id = repo.list_items(job.id)[0].id

        ctx = {
            "session_factory": _factory(session),
            "publisher": _SpyPublisher(),
            "client_pool": None,
            "now": NOW,
        }
        await item_impl(ctx, job.id, item_id)

        session.expire_all()
        it = repo.get_item(item_id)
        assert it.status == BulkItemStatus.FAILED.value
        assert it.error and "kaboom" in it.error

        updated = repo.get(job.id)
        assert updated.failed_count == 1
        assert updated.status == BulkJobStatus.FAILED.value
    finally:
        if original is not None:
            ACTION_REGISTRY[_TEST_ACTION_NAME] = original


# ── 5. cancel останавливает pending, retry-failed переоткрывает failed ───────


async def test_cancel_marks_pending_cancelled(session):
    _clean(session)
    a1 = _make_account(session)
    a2 = _make_account(session)
    repo = BulkJobRepository(session)
    job = repo.create(
        action_type=_TEST_ACTION_NAME,
        payload={},
        initiator="u",
        account_ids=[a1, a2],
    )
    session.commit()

    repo.cancel(job.id, now=NOW)
    session.commit()
    session.expire_all()

    updated = repo.get(job.id)
    assert updated.status == BulkJobStatus.CANCELLED.value
    for it in repo.list_items(job.id):
        assert it.status == BulkItemStatus.CANCELLED.value


def test_retry_failed_resets_failed_items(session):
    _clean(session)
    a = _make_account(session)
    repo = BulkJobRepository(session)
    job = repo.create(
        action_type=_TEST_ACTION_NAME,
        payload={},
        initiator="u",
        account_ids=[a],
    )
    session.commit()
    item_id = repo.list_items(job.id)[0].id
    repo.apply_item_result(
        item_id,
        status=BulkItemStatus.FAILED,
        error="boom",
        finished_at=NOW,
    )
    repo.recompute_counters(job.id)
    session.commit()

    reset = repo.reset_failed_to_pending(job.id)
    session.commit()
    assert reset == 1
    session.expire_all()
    it = repo.get_item(item_id)
    assert it.status == BulkItemStatus.PENDING.value
    assert it.error is None
    assert repo.get(job.id).status == BulkJobStatus.QUEUED.value
