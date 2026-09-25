"""Тесты исполнителя шага шиллинга. БД настоящая (CI/postgres); Telethon,
ClientPool, governor, LLM — фейки; now/rng инъектируются."""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.models import Account
from core.queue.task_names import TaskName
from modules.shilling.repositories import (
    CampaignRepository,
    CampaignTargetRepository,
    ExecutionLogRepository,
    ScenarioRepository,
    ScenarioRoleRepository,
    ScenarioStepRepository,
)
from modules.shilling.schemas import (
    CampaignCreate,
    RoleCreate,
    ScenarioCreate,
    StepCreate,
    TargetCreate,
)
from modules.shilling.worker import executor
from modules.shilling.worker.executor import _is_ban_like

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
_PHONE = itertools.count(97_000_000_000)


# --- фейки -------------------------------------------------------------------


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
        assert action_type == "shilling"
        return self.allow


class _FakeLLM:
    async def generate(self, system, messages, max_tokens=200, temperature=0.8):
        return "переписанная реплика с брендом"


class _OkClient:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_to=None):
        self.sent.append((chat_id, text, reply_to))
        return SimpleNamespace(id=555)


class _BanClient:
    async def send_message(self, chat_id, text, reply_to=None):
        # имитируем бан-подобную ошибку по имени класса
        raise type("UserBannedInChannelError", (Exception,), {})()


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


def make_campaign_with_step(session, *, phone: int) -> dict:
    """Собирает кампанию (running) + сценарий с одной репликой + цель + аккаунт.

    Возвращает словарь id'шников для теста.
    """
    campaign = CampaignRepository(session).create(
        CampaignCreate(name="camp", brand_name="Beauty Zone", unique_messages=False)
    )
    session.flush()
    scenario = ScenarioRepository(session).create(
        ScenarioCreate(campaign_id=campaign.id, persons_count=2)
    )
    session.flush()
    role = ScenarioRoleRepository(session).create(
        scenario.id, RoleCreate(name="Ответчик", character="делится опытом")
    )
    session.flush()
    step = ScenarioStepRepository(session).create(
        scenario.id,
        StepCreate(role_id=role.id, step_type="message", text="Ходила в Beauty Zone"),
    )
    target = CampaignTargetRepository(session).create(
        campaign.id, TargetCreate(raw_input="beauty_chat", kind="username")
    )
    session.flush()
    CampaignTargetRepository(session).mark_resolved(
        target.id, resolved_chat_id=-100500, title="Beauty Chat"
    )
    CampaignRepository(session).set_status(campaign.id, "running")

    acc = Account(
        phone=str(phone),
        session_enc=b"x",
        status="assigned",
        device_model="Pixel",
        system_version="13",
        app_version="10.0",
        lang_code="ru",
        system_lang_code="ru-RU",
    )
    session.add(acc)
    session.commit()
    return {
        "campaign_id": campaign.id,
        "scenario_id": scenario.id,
        "role_id": role.id,
        "step_id": step.id,
        "target_id": target.id,
        "chat_id": -100500,
        "account_id": acc.id,
    }


def _ctx(session, *, client, governor=None, llm=None, task_queue=None):
    return {
        "session_factory": _factory(session),
        "now": NOW,
        "task_queue": task_queue or _SpyTaskQueue(),
        "client_pool": _FakePool(client),
        "governor": governor or _FakeGovernor(),
        "llm_provider": llm or _FakeLLM(),
        "publisher": None,
    }


# --- pure unit: классификация ошибок -----------------------------------------


def test_is_ban_like_matches_known_names():
    for name in ("PeerFloodError", "UserBannedInChannelError", "ChatWriteForbiddenError"):
        exc = type(name, (Exception,), {})()
        assert _is_ban_like(exc)


def test_is_ban_like_ignores_others():
    assert not _is_ban_like(ValueError("x"))


# --- интеграция (postgres) ---------------------------------------------------


async def test_execute_step_sends_and_logs(session):
    ids = make_campaign_with_step(session, phone=next(_PHONE))
    client = _OkClient()
    ctx = _ctx(session, client=client)

    sent_id = await executor.execute_step(
        ctx, ids["campaign_id"], ids["target_id"], ids["step_id"], ids["account_id"],
        thread_msg_id=100,
    )
    assert sent_id == 555
    assert client.sent and client.sent[0][0] == ids["chat_id"]
    logs = ExecutionLogRepository(session).list_by_campaign(ids["campaign_id"])
    assert len(logs) == 1 and logs[0].status == "sent" and logs[0].posted_message_id == 555


async def test_execute_step_rate_limited_reschedules(session):
    ids = make_campaign_with_step(session, phone=next(_PHONE))
    spy = _SpyTaskQueue()
    ctx = _ctx(session, client=_OkClient(), governor=_FakeGovernor(allow=False), task_queue=spy)

    result = await executor.execute_step(
        ctx, ids["campaign_id"], ids["target_id"], ids["step_id"], ids["account_id"],
        thread_msg_id=100,
    )
    assert result is None
    assert spy.scheduled and spy.scheduled[0][0] == TaskName.SHILLING_EXECUTE_STEP


async def test_execute_step_ban_triggers_failover(session):
    ids = make_campaign_with_step(session, phone=next(_PHONE))
    spy = _SpyTaskQueue()
    ctx = _ctx(session, client=_BanClient(), task_queue=spy)

    result = await executor.execute_step(
        ctx, ids["campaign_id"], ids["target_id"], ids["step_id"], ids["account_id"],
        thread_msg_id=100,
    )
    assert result is None
    # failover опубликован
    names = [n for n, _, _ in spy.enqueued]
    assert TaskName.SHILLING_FAILOVER in names
    # лог failed записан
    logs = ExecutionLogRepository(session).list_by_campaign(ids["campaign_id"])
    assert any(l.status == "failed" for l in logs)
