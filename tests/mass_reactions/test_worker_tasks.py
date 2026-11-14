"""Шаг 5c: arq-хендлер orchestrator_tick (раскладка, финиш, reschedule)."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone

from core.models import Account, MassReactionCampaign
from modules.mass_reactions.repositories import (
    CampaignAccountRepository,
    CampaignChatRepository,
)
from modules.mass_reactions.schemas.enums import MassReactionCampaignStatus
from modules.mass_reactions.schemas.enums import ChatState
from modules.mass_reactions.worker.tasks import (
    orchestrator_tick_task,
    resolve_pending_chats,
)


class _FakeQueue:
    def __init__(self):
        self.scheduled = []

    async def schedule(self, name, run_at, *args):
        self.scheduled.append((getattr(name, "value", name), run_at, args))


def _ctx(session):
    @contextlib.contextmanager
    def factory():
        yield session
    return {"session_factory": factory, "task_queue": _FakeQueue()}


def _account(session, n):
    a = Account(
        phone=f"+79000{n:05d}", session_enc=b"e", status="assigned",
        device_model="iPhone15,3", system_version="17", app_version="10",
        lang_code="uk", system_lang_code="uk-UA",
    )
    session.add(a)
    session.flush()
    return a


def _run(coro):
    return asyncio.run(coro)


def test_tick_assigns_and_reschedules(session):
    c = MassReactionCampaign(
        name="mr", reaction_emojis=["👍"], max_chats_per_account=2,
        status=MassReactionCampaignStatus.RUNNING.value,
    )
    session.add(c)
    session.flush()
    a = _account(session, 1)
    CampaignAccountRepository(session).create({"campaign_id": c.id, "account_id": a.id})
    chats = CampaignChatRepository(session)
    for i in range(2):
        chats.create({"campaign_id": c.id, "chat_ref": f"@c{i}"})

    ctx = _ctx(session)
    res = _run(orchestrator_tick_task(ctx, c.id))
    assert res == {"assigned": 2}
    # следующий tick запланирован
    assert ctx["task_queue"].scheduled
    assert ctx["task_queue"].scheduled[0][0] == "mass_reactions.orchestrator_tick"


def test_tick_finishes_expired(session):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    c = MassReactionCampaign(
        name="mr", reaction_emojis=["👍"],
        status=MassReactionCampaignStatus.RUNNING.value,
        started_at=past - timedelta(hours=1), expires_at=past,
    )
    session.add(c)
    session.flush()
    ctx = _ctx(session)
    res = _run(orchestrator_tick_task(ctx, c.id))
    assert res == {"finished": True}
    session.refresh(c)
    assert c.status == MassReactionCampaignStatus.FINISHED.value
    # финиш не планирует следующий tick
    assert ctx["task_queue"].scheduled == []


class _Entity:
    def __init__(self, id, title=None):
        self.id = id
        self.title = title


class _FakeClient:
    def __init__(self, entity):
        self._entity = entity

    async def get_entity(self, ref):
        return self._entity


class _FakePool:
    def __init__(self, client):
        self._client = client

    async def get(self, account_id):
        return self._client

    async def release(self, account_id):
        pass


def test_resolve_by_subscriptions_activates_chat(session):
    c = MassReactionCampaign(
        name="mr", reaction_emojis=["👍"],
        chat_source_mode="by_subscriptions",
        status=MassReactionCampaignStatus.RUNNING.value,
    )
    session.add(c)
    session.flush()
    a = _account(session, 7)
    chat = CampaignChatRepository(session).create({
        "campaign_id": c.id, "chat_ref": "@target", "account_id": a.id,
    })
    session.flush()

    ctx = _ctx(session)
    ctx["client_pool"] = _FakePool(_FakeClient(_Entity(555, "Target")))
    n = _run(resolve_pending_chats(ctx, campaign_id=c.id, chat_source_mode="by_subscriptions"))
    assert n == 1
    session.refresh(chat)
    assert chat.state == ChatState.ACTIVE.value
    assert chat.chat_tg_id == 555
    assert chat.title == "Target"


def test_resolve_explicit_notify_only_marks_not_subscribed(session):
    c = MassReactionCampaign(
        name="mr", reaction_emojis=["👍"],
        chat_source_mode="explicit_list",
        status=MassReactionCampaignStatus.RUNNING.value,
    )
    session.add(c)
    session.flush()
    a = _account(session, 8)
    chat = CampaignChatRepository(session).create({
        "campaign_id": c.id, "chat_ref": "@ext", "account_id": a.id,
        "notify_mode": "notify_only",
    })
    session.flush()

    ctx = _ctx(session)
    ctx["client_pool"] = _FakePool(_FakeClient(_Entity(777)))
    _run(resolve_pending_chats(ctx, campaign_id=c.id, chat_source_mode="explicit_list"))
    session.refresh(chat)
    assert chat.state == ChatState.NOT_SUBSCRIBED.value
    assert chat.chat_tg_id == 777


def test_tick_noop_when_not_running(session):
    c = MassReactionCampaign(
        name="mr", reaction_emojis=["👍"],
        status=MassReactionCampaignStatus.PAUSED.value,
    )
    session.add(c)
    session.flush()
    ctx = _ctx(session)
    res = _run(orchestrator_tick_task(ctx, c.id))
    assert res == {"stopped": True}
    assert ctx["task_queue"].scheduled == []
