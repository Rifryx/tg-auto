"""Тесты сухого прогона. БД настоящая (CI/postgres); Telethon/LLM — фейки."""

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
from modules.shilling.worker import dry_run as dry_run_mod
from modules.shilling.worker.dry_run import dry_run, dry_run_channel

pytestmark = pytest.mark.asyncio

_PHONE = itertools.count(90_100_000_000)


class _FakePublisher:
    def __init__(self):
        self.events = []

    def publish(self, channel, payload):
        self.events.append((channel, payload))


class _FakePool:
    def __init__(self, client):
        self._client = client
        self.released = []
        self.sent = []  # чтобы доказать, что реальной отправки НЕ было

    async def get(self, account_id):
        return self._client

    async def release(self, account_id):
        self.released.append(account_id)


class _DiscussionClient:
    async def get_entity(self, ref):
        return SimpleNamespace(id=-100, title="C", username="chan")

    async def get_messages(self, entity, limit=1):
        return [SimpleNamespace(id=42)]

    async def __call__(self, request):
        name = type(request).__name__
        if "GetFullChannel" in name:
            return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=-200))
        if "GetDiscussionMessage" in name:
            return SimpleNamespace(messages=[SimpleNamespace(id=777)])
        return None

    # намеренно НЕТ send_message: если dry-run попытается отправить — упадёт


class _NoDiscussionClient(_DiscussionClient):
    async def __call__(self, request):
        if "GetFullChannel" in type(request).__name__:
            return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=None))
        return None


class _Rng:
    def uniform(self, a, b):
        return a

    def choice(self, seq):
        return seq[0]


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


def _setup(session, *, unique=False):
    campaign = CampaignRepository(session).create(
        CampaignCreate(name="c", brand_name="B", unique_messages=unique,
                       reply_delay_min_sec=5, reply_delay_max_sec=5)
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
    CampaignRepository(session).set_status(campaign.id, "running")
    session.commit()
    return campaign.id


def _ctx(session, client, publisher):
    return {
        "session_factory": _factory(session),
        "now": None,
        "rng": _Rng(),
        "client_pool": _FakePool(client),
        "publisher": publisher,
    }


async def test_dry_run_simulates_without_sending(session):
    cid = _setup(session)
    pub = _FakePublisher()
    report = await dry_run(_ctx(session, _DiscussionClient(), pub), cid, "@test", "job1")

    assert report.ok is True
    assert report.total_messages == 2 and report.total_reactions == 0
    assert len(report.timeline) == 2
    assert report.duration_sec == 10  # 2 шага по 5 сек
    # события опубликованы в per-job канал
    channels = {c for c, _ in pub.events}
    assert channels == {dry_run_channel("job1")}
    kinds = [p["event"] for _, p in pub.events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert kinds.count("step") == 2


async def test_dry_run_no_discussion_fails(session):
    cid = _setup(session)
    pub = _FakePublisher()
    report = await dry_run(_ctx(session, _NoDiscussionClient(), pub), cid, "@test", "job2")
    assert report.ok is False
    assert "comments" in (report.reason or "")
    # финальное done-событие всё равно опубликовано
    assert pub.events and pub.events[-1][1]["event"] == "done"


async def test_dry_run_not_ready_fails(session):
    campaign = CampaignRepository(session).create(CampaignCreate(name="empty", brand_name="B"))
    session.flush()
    CampaignRepository(session).set_status(campaign.id, "running")
    session.commit()
    pub = _FakePublisher()
    report = await dry_run(_ctx(session, _DiscussionClient(), pub), campaign.id, "@t", "job3")
    assert report.ok is False and "not ready" in (report.reason or "")


async def test_dry_run_unique_estimates_tokens(session):
    cid = _setup(session, unique=True)
    pub = _FakePublisher()

    class _LLM:
        async def generate(self, system, messages, max_tokens=200, temperature=0.8):
            return "переписанный текст с B"

    ctx = _ctx(session, _DiscussionClient(), pub)
    ctx["llm_provider"] = _LLM()
    report = await dry_run(ctx, cid, "@test", "job4")
    assert report.ok is True
    assert report.estimated_tokens == 2 * dry_run_mod._TOKENS_PER_STEP
