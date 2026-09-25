"""Тесты ротации резерва (failover). БД настоящая (CI/postgres); задачи — spy."""

from __future__ import annotations

import itertools

import pytest

from core.models import Account
from core.queue.task_names import TaskName
from modules.shilling.repositories import (
    BlacklistRepository,
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
    ExecutionLogRepository,
    ScenarioRepository,
    ScenarioRoleRepository,
)
from modules.shilling.schemas import (
    CampaignCreate,
    ExecutionLogCreate,
    RoleCreate,
    ScenarioCreate,
    TargetCreate,
)
from modules.shilling.worker import orchestrator

pytestmark = pytest.mark.asyncio

_PHONE = itertools.count(98_000_000_000)


class _SpyTaskQueue:
    def __init__(self):
        self.enqueued = []

    async def enqueue(self, name, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
        return "job"


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


def _acc(session, *, status="assigned") -> int:
    acc = Account(
        phone=str(next(_PHONE)),
        session_enc=b"x",
        status=status,
        device_model="Pixel",
        system_version="13",
        app_version="10",
        lang_code="ru",
        system_lang_code="ru-RU",
    )
    session.add(acc)
    session.flush()
    return acc.id


def _setup(session, *, reserve_enabled=True, with_reserve=True):
    campaign = CampaignRepository(session).create(
        CampaignCreate(name="c", brand_name="B", reserve_enabled=reserve_enabled)
    )
    session.flush()
    scenario = ScenarioRepository(session).create(
        ScenarioCreate(campaign_id=campaign.id, persons_count=2)
    )
    session.flush()
    role = ScenarioRoleRepository(session).create(scenario.id, RoleCreate(name="Ответчик"))
    session.flush()
    target = CampaignTargetRepository(session).create(
        campaign.id, TargetCreate(raw_input="chat", kind="username")
    )
    session.flush()
    CampaignTargetRepository(session).mark_resolved(target.id, resolved_chat_id=-100, title="C")
    CampaignRepository(session).set_status(campaign.id, "running")

    link_repo = CampaignAccountRepository(session)
    primary_id = _acc(session)
    link_repo.attach(campaign.id, primary_id, role_id=role.id, is_reserve=False)
    reserve_id = None
    if with_reserve:
        reserve_id = _acc(session)
        link_repo.attach(campaign.id, reserve_id, role_id=None, is_reserve=True)
    session.commit()
    return {
        "campaign_id": campaign.id,
        "role_id": role.id,
        "target_id": target.id,
        "step_id": 1,  # фиктивный, failover его не читает
        "primary_id": primary_id,
        "reserve_id": reserve_id,
    }


async def test_failover_promotes_reserve(session):
    ids = _setup(session)
    spy = _SpyTaskQueue()
    ctx = {"session_factory": _factory(session), "task_queue": spy, "publisher": None}

    new_id = await orchestrator.failover(
        ctx, ids["campaign_id"], ids["target_id"], ids["step_id"], ids["primary_id"]
    )
    assert new_id == ids["reserve_id"]
    # execute_step перезапущен новым аккаунтом
    assert spy.enqueued and spy.enqueued[0][0] == TaskName.SHILLING_EXECUTE_STEP
    assert spy.enqueued[0][1][3] == ids["reserve_id"]
    # резерв повышен, выбывший отвязан
    link_repo = CampaignAccountRepository(session)
    promoted = link_repo.get_link(ids["campaign_id"], ids["reserve_id"])
    assert promoted.is_reserve is False and promoted.role_id == ids["role_id"]
    assert link_repo.get_link(ids["campaign_id"], ids["primary_id"]) is None


async def test_failover_exhausted_blacklists_target(session):
    ids = _setup(session, with_reserve=False)
    spy = _SpyTaskQueue()
    ctx = {"session_factory": _factory(session), "task_queue": spy, "publisher": None}

    new_id = await orchestrator.failover(
        ctx, ids["campaign_id"], ids["target_id"], ids["step_id"], ids["primary_id"]
    )
    assert new_id is None
    assert not spy.enqueued
    bl = BlacklistRepository(session).list_by_campaign(ids["campaign_id"])
    assert len(bl) == 1 and bl[0].auto is True


async def test_failover_reserve_disabled_blacklists(session):
    ids = _setup(session, reserve_enabled=False, with_reserve=True)
    spy = _SpyTaskQueue()
    ctx = {"session_factory": _factory(session), "task_queue": spy, "publisher": None}

    new_id = await orchestrator.failover(
        ctx, ids["campaign_id"], ids["target_id"], ids["step_id"], ids["primary_id"]
    )
    assert new_id is None
    assert not spy.enqueued
    bl = BlacklistRepository(session).list_by_campaign(ids["campaign_id"])
    assert len(bl) == 1 and bl[0].auto is True


async def test_failover_skips_reserve_that_already_failed(session):
    ids = _setup(session)
    # резерв уже провалился на этой цели → не должен быть выбран
    ExecutionLogRepository(session).create(
        ExecutionLogCreate(
            campaign_id=ids["campaign_id"],
            target_id=ids["target_id"],
            account_id=ids["reserve_id"],
            status="failed",
            error="UserBannedInChannelError",
        )
    )
    session.commit()
    spy = _SpyTaskQueue()
    ctx = {"session_factory": _factory(session), "task_queue": spy, "publisher": None}

    new_id = await orchestrator.failover(
        ctx, ids["campaign_id"], ids["target_id"], ids["step_id"], ids["primary_id"]
    )
    # единственный резерв уже провалился → замены нет, цель в ЧС
    assert new_id is None
    bl = BlacklistRepository(session).list_by_campaign(ids["campaign_id"])
    assert len(bl) == 1 and bl[0].auto is True
