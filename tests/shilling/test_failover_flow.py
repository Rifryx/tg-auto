"""Flow-тест ротации: executor ловит бан → failover → резерв завершает шаг.

БД настоящая (CI/postgres). Telethon/governor/LLM — фейки.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest

from core.models import Account
from core.queue.task_names import TaskName
from modules.shilling.repositories import (
    CampaignAccountRepository,
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
from modules.shilling.worker import executor, orchestrator

pytestmark = pytest.mark.asyncio

_PHONE = itertools.count(90_700_000_000)


class _SpyTaskQueue:
    def __init__(self):
        self.enqueued = []
        self.scheduled = []

    async def enqueue(self, name, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
        return "job"

    async def schedule(self, name, *a, **k):
        self.scheduled.append((name, a, k))
        return "job"


class _BanClient:
    async def send_message(self, chat_id, text, reply_to=None):
        raise type("UserBannedInChannelError", (Exception,), {})()


class _OkClient:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_to=None):
        self.sent.append((chat_id, text, reply_to))
        return SimpleNamespace(id=999)


class _SwitchPool:
    """Отдаёт разные клиенты по account_id."""

    def __init__(self, mapping):
        self.mapping = mapping

    async def get(self, account_id):
        return self.mapping[account_id]

    async def release(self, account_id):
        pass


class _Gov:
    async def check_and_reserve(self, a, t):
        return True


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *e):
            return False

    return lambda: _Ctx()


def _acc(session) -> int:
    a = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="assigned",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(a)
    session.flush()
    return a.id


async def test_ban_triggers_failover_and_reserve_completes(session):
    campaign = CampaignRepository(session).create(
        CampaignCreate(name="c", brand_name="B", unique_messages=False)
    )
    session.flush()
    scenario = ScenarioRepository(session).create(
        ScenarioCreate(campaign_id=campaign.id, persons_count=2)
    )
    session.flush()
    role = ScenarioRoleRepository(session).create(scenario.id, RoleCreate(name="Ответчик"))
    session.flush()
    step = ScenarioStepRepository(session).create(
        scenario.id, StepCreate(role_id=role.id, step_type="message", text="Ответ про B")
    )
    target = CampaignTargetRepository(session).create(
        campaign.id, TargetCreate(raw_input="chat", kind="username")
    )
    session.flush()
    CampaignTargetRepository(session).mark_resolved(target.id, resolved_chat_id=-200)
    CampaignRepository(session).set_status(campaign.id, "running")

    primary_id = _acc(session)
    reserve_id = _acc(session)
    links = CampaignAccountRepository(session)
    links.attach(campaign.id, primary_id, role_id=role.id, is_reserve=False)
    links.attach(campaign.id, reserve_id, role_id=None, is_reserve=True)
    session.commit()

    spy = _SpyTaskQueue()
    pool = _SwitchPool({primary_id: _BanClient(), reserve_id: _OkClient()})
    ctx = {
        "session_factory": _factory(session),
        "now": None,
        "task_queue": spy,
        "client_pool": pool,
        "governor": _Gov(),
        "publisher": None,
    }

    # 1) Основной аккаунт банится → executor логирует failed + шлёт failover.
    res = await executor.execute_step(
        ctx, campaign.id, target.id, step.id, primary_id, thread_msg_id=777
    )
    assert res is None
    fo = [e for e in spy.enqueued if e[0] == TaskName.SHILLING_FAILOVER]
    assert len(fo) == 1
    logs = ExecutionLogRepository(session).list_by_campaign(campaign.id)
    assert any(l.status == "failed" and l.account_id == primary_id for l in logs)

    # 2) failover(...) с аргументами из очереди → повышает резерв + шлёт execute_step.
    _, args, kwargs = fo[0]
    spy.enqueued.clear()
    new_id = await orchestrator.failover(ctx, *args, **kwargs)
    assert new_id == reserve_id
    ex = [e for e in spy.enqueued if e[0] == TaskName.SHILLING_EXECUTE_STEP]
    assert len(ex) == 1 and ex[0][1][3] == reserve_id
    # резерв повышен на роль, основной отвязан
    promoted = links.get_link(campaign.id, reserve_id)
    assert promoted.is_reserve is False and promoted.role_id == role.id
    assert links.get_link(campaign.id, primary_id) is None

    # 3) execute_step резервом → успех.
    _, ex_args, ex_kwargs = ex[0]
    sent = await executor.execute_step(ctx, *ex_args, **ex_kwargs)
    assert sent == 999
    logs = ExecutionLogRepository(session).list_by_campaign(campaign.id)
    assert any(l.status == "sent" and l.account_id == reserve_id for l in logs)
