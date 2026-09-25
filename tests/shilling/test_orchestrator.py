"""Тесты оркестратора: start_campaign + process_target.

БД настоящая (CI/postgres); Telethon/ClientPool — фейки; now/rng инъектируются.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.models import Account
from core.queue.task_names import TaskName
from modules.shilling.repositories import (
    BlacklistRepository,
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
    ScenarioRepository,
    ScenarioRoleRepository,
    ScenarioStepRepository,
)
from modules.shilling.schemas import (
    BlacklistCreate,
    CampaignCreate,
    RoleCreate,
    ScenarioCreate,
    StepCreate,
    TargetCreate,
)
from modules.shilling.worker import orchestrator

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
_PHONE = itertools.count(99_000_000_000)


class _Rng:
    def uniform(self, a, b):
        return a  # детерминизм

    def choice(self, seq):
        return seq[0]


class _SpyTaskQueue:
    def __init__(self):
        self.scheduled = []

    async def schedule(self, name, run_at, *args, **kwargs):
        self.scheduled.append((name, run_at, args, kwargs))
        return "job"

    async def enqueue(self, name, *args, **kwargs):
        self.scheduled.append((name, None, args, kwargs))
        return "job"


class _FakePool:
    def __init__(self, client):
        self._client = client
        self.released = []

    async def get(self, account_id):
        return self._client

    async def release(self, account_id):
        self.released.append(account_id)


class _DiscussionClient:
    """Фейк Telethon: канал с discussion-группой и одним постом."""

    def __init__(self, linked=-200, post_id=42, root_id=777):
        self._linked, self._post_id, self._root_id = linked, post_id, root_id

    async def get_entity(self, ref):
        return SimpleNamespace(id=-100, title="Channel", username="chan")

    async def get_messages(self, entity, limit=1):
        return [SimpleNamespace(id=self._post_id)]

    async def __call__(self, request):
        name = type(request).__name__
        if "GetFullChannel" in name:
            return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=self._linked))
        if "GetDiscussionMessage" in name:
            return SimpleNamespace(messages=[SimpleNamespace(id=self._root_id)])
        return None


class _NoDiscussionClient(_DiscussionClient):
    async def __call__(self, request):
        if "GetFullChannel" in type(request).__name__:
            return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=None))
        return None


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


def _acc(session) -> int:
    acc = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="assigned",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(acc)
    session.flush()
    return acc.id


def _setup(session, *, n_targets=1, running=True):
    campaign = CampaignRepository(session).create(
        CampaignCreate(name="c", brand_name="B", target_delay_min_sec=100,
                       target_delay_max_sec=100, reply_delay_min_sec=5, reply_delay_max_sec=5)
    )
    session.flush()
    scenario = ScenarioRepository(session).create(
        ScenarioCreate(campaign_id=campaign.id, persons_count=2)
    )
    session.flush()
    r1 = ScenarioRoleRepository(session).create(scenario.id, RoleCreate(name="Инициатор"))
    r2 = ScenarioRoleRepository(session).create(scenario.id, RoleCreate(name="Ответчик"))
    session.flush()
    ScenarioStepRepository(session).create(
        scenario.id, StepCreate(role_id=r1.id, step_type="message", text="вопрос?")
    )
    ScenarioStepRepository(session).create(
        scenario.id, StepCreate(role_id=r2.id, step_type="message", text="ответ про B")
    )
    link_repo = CampaignAccountRepository(session)
    link_repo.attach(campaign.id, _acc(session), role_id=r1.id, is_reserve=False)
    link_repo.attach(campaign.id, _acc(session), role_id=r2.id, is_reserve=False)
    target_ids = []
    for i in range(n_targets):
        t = CampaignTargetRepository(session).create(
            campaign.id, TargetCreate(raw_input=f"chan{i}", kind="username")
        )
        session.flush()
        target_ids.append(t.id)
    if running:
        CampaignRepository(session).set_status(campaign.id, "running")
    session.commit()
    return {"campaign_id": campaign.id, "scenario_id": scenario.id, "target_ids": target_ids}


def _ctx(session, *, client=None, task_queue=None):
    return {
        "session_factory": _factory(session),
        "now": NOW,
        "rng": _Rng(),
        "task_queue": task_queue or _SpyTaskQueue(),
        "client_pool": _FakePool(client) if client is not None else None,
        "publisher": None,
    }


# --- start_campaign ----------------------------------------------------------


async def test_start_campaign_schedules_all_targets(session):
    ids = _setup(session, n_targets=3)
    spy = _SpyTaskQueue()
    count = await orchestrator.start_campaign(_ctx(session, task_queue=spy), ids["campaign_id"])
    assert count == 3
    names = [n for n, _, _, _ in spy.scheduled]
    assert names == [TaskName.SHILLING_PROCESS_TARGET] * 3


async def test_start_campaign_not_ready_sets_error(session):
    # кампания без сценария/аккаунтов
    campaign = CampaignRepository(session).create(CampaignCreate(name="empty", brand_name="B"))
    session.flush()
    CampaignRepository(session).set_status(campaign.id, "running")
    session.commit()
    spy = _SpyTaskQueue()
    count = await orchestrator.start_campaign(_ctx(session, task_queue=spy), campaign.id)
    assert count == 0
    assert not spy.scheduled
    assert CampaignRepository(session).get(campaign.id).status == "error"


# --- process_target ----------------------------------------------------------


async def test_process_target_schedules_steps(session):
    ids = _setup(session)
    spy = _SpyTaskQueue()
    ctx = _ctx(session, client=_DiscussionClient(), task_queue=spy)
    count = await orchestrator.process_target(ctx, ids["campaign_id"], ids["target_ids"][0])
    assert count == 2
    names = [n for n, _, _, _ in spy.scheduled]
    assert names == [TaskName.SHILLING_EXECUTE_STEP] * 2
    # thread_msg_id == root обсуждения (777)
    assert all(kw["thread_msg_id"] == 777 for _, _, _, kw in spy.scheduled)
    # target получил resolved_chat_id = discussion group (-200)
    t = CampaignTargetRepository(session).get(ids["target_ids"][0])
    assert t.resolved_chat_id == -200


async def test_process_target_no_discussion_blacklists(session):
    ids = _setup(session)
    spy = _SpyTaskQueue()
    ctx = _ctx(session, client=_NoDiscussionClient(), task_queue=spy)
    count = await orchestrator.process_target(ctx, ids["campaign_id"], ids["target_ids"][0])
    assert count == 0
    assert not spy.scheduled
    bl = BlacklistRepository(session).list_by_campaign(ids["campaign_id"])
    assert len(bl) == 1 and bl[0].auto is True


async def test_process_target_skips_blacklisted(session):
    ids = _setup(session)
    # заносим цель (username) в ЧС заранее
    BlacklistRepository(session).create(
        ids["campaign_id"], BlacklistCreate(username="chan0"), auto=False
    )
    session.commit()
    spy = _SpyTaskQueue()
    ctx = _ctx(session, client=_DiscussionClient(), task_queue=spy)
    count = await orchestrator.process_target(ctx, ids["campaign_id"], ids["target_ids"][0])
    assert count == 0
    assert not spy.scheduled
