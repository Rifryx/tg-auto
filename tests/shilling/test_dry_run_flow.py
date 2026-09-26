"""Flow-тест сухого прогона: реального постинга НЕ происходит, тайминги верны.

БД настоящая (CI/postgres). Telethon/LLM — фейки.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest

from core.models import Account
from modules.shilling.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    ScenarioRepository,
    ScenarioRoleRepository,
    ScenarioStepRepository,
)
from modules.shilling.schemas import (
    CampaignCreate,
    RoleCreate,
    ScenarioCreate,
    StepCreate,
)
from modules.shilling.worker.dry_run import dry_run

pytestmark = pytest.mark.asyncio

_PHONE = itertools.count(90_900_000_000)


class _SpyClient:
    """Резолвит канал; send_message ЗАПРЕЩЁН (сухой прогон не постит)."""

    def __init__(self):
        self.sent = []

    async def get_entity(self, ref):
        return SimpleNamespace(id=-100, title="C", username="chan")

    async def get_messages(self, entity, limit=1):
        return [SimpleNamespace(id=42)]

    async def __call__(self, request):
        n = type(request).__name__
        if "GetFullChannel" in n:
            return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=-200))
        if "GetDiscussionMessage" in n:
            return SimpleNamespace(messages=[SimpleNamespace(id=777)])
        return None

    async def send_message(self, *a, **k):
        self.sent.append((a, k))
        raise AssertionError("dry-run must NOT send messages")


class _FakePool:
    def __init__(self, client):
        self._client = client

    async def get(self, account_id):
        return self._client

    async def release(self, account_id):
        pass


class _Rng:
    def uniform(self, a, b):
        return a

    def choice(self, seq):
        return seq[0]


class _Pub:
    def __init__(self):
        self.events = []

    def publish(self, channel, payload):
        self.events.append((channel, payload))


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


async def test_dry_run_does_not_send_and_reports_timeline(session):
    campaign = CampaignRepository(session).create(
        CampaignCreate(
            name="c", brand_name="B", unique_messages=False,
            reply_delay_min_sec=7, reply_delay_max_sec=7,
        )
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
    links = CampaignAccountRepository(session)
    links.attach(campaign.id, _acc(session), role_id=r1.id, is_reserve=False)
    links.attach(campaign.id, _acc(session), role_id=r2.id, is_reserve=False)
    CampaignRepository(session).set_status(campaign.id, "running")
    session.commit()

    client = _SpyClient()
    pub = _Pub()
    ctx = {
        "session_factory": _factory(session),
        "now": None,
        "rng": _Rng(),
        "client_pool": _FakePool(client),
        "publisher": pub,
    }

    report = await dry_run(ctx, campaign.id, "@test", "job-x")

    # Ничего не отправлено.
    assert client.sent == []
    # Отчёт: 2 сообщения, тайминги 7 и 14 сек (по 7с на реплику).
    assert report.ok is True
    assert report.total_messages == 2 and report.total_reactions == 0
    assert [s.scheduled_at_sec for s in report.timeline] == [7, 14]
    # События start/step/done в per-job канал.
    kinds = [p["event"] for _, p in pub.events]
    assert kinds[0] == "start" and kinds[-1] == "done" and kinds.count("step") == 2
