"""Тесты trust-graph и interact_with_peer action (этап 10, backlog #2)."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from core.config import get_settings
from core.enums import WarmingActionType, WarmingActivityStatus
from core.models import Account, Persona, Project
from modules.commenting.models import Campaign, CampaignAccount
from worker.warming.trust_graph import (
    collect_campaign_ids,
    find_trust_peer_username,
)

pytestmark = pytest.mark.asyncio


_TABLES = (
    "autopilot_actions",
    "autopilot_goals",
    "project_channels",
    "bulk_job_items",
    "bulk_jobs",
    "accounts",
    "personas",
    "projects",
    "warming_activities",
    '"commenting".campaign_accounts',
    '"commenting".campaigns',
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _make_account(session, phone, *, username=None, project_id=None,
                  persona_id=None, status="pool"):
    a = Account(
        phone=phone, session_enc=b"e",
        status=status, username=username,
        project_id=project_id, persona_id=persona_id,
        device_model="d", system_version="v", app_version="a",
        lang_code="uk", system_lang_code="uk-UA",
    )
    session.add(a)
    session.flush()
    session.commit()
    return a


# ── find_trust_peer_username ────────────────────────────────────────────────


def test_find_peer_returns_none_when_no_identifiers(session):
    _clean(session)
    account = _make_account(session, "+1")
    got = find_trust_peer_username(
        session, account.id, project_id=None, persona_id=None, campaign_ids=None
    )
    assert got is None


def test_find_peer_by_project(session):
    _clean(session)
    project = Project(user_id="u", name="P")
    session.add(project)
    session.commit()

    me = _make_account(session, "+1", project_id=project.id)
    peer = _make_account(session, "+2", project_id=project.id, username="peer1")

    got = find_trust_peer_username(
        session, me.id, project_id=project.id, persona_id=None, campaign_ids=None
    )
    assert got == "peer1"


def test_find_peer_by_persona(session):
    _clean(session)
    persona = Persona(name="P", personality_tags=[])
    session.add(persona)
    session.commit()

    me = _make_account(session, "+1", persona_id=persona.id)
    _make_account(session, "+2", persona_id=persona.id, username="pp")

    got = find_trust_peer_username(
        session, me.id, project_id=None, persona_id=persona.id, campaign_ids=None
    )
    assert got == "pp"


def test_find_peer_excludes_no_username(session):
    _clean(session)
    project = Project(user_id="u", name="P")
    session.add(project)
    session.commit()

    me = _make_account(session, "+1", project_id=project.id)
    # peer without username — не подходит:
    _make_account(session, "+2", project_id=project.id, username=None)

    got = find_trust_peer_username(
        session, me.id, project_id=project.id, persona_id=None, campaign_ids=None
    )
    assert got is None


def test_find_peer_excludes_banned_and_retired(session):
    _clean(session)
    project = Project(user_id="u", name="P")
    session.add(project)
    session.commit()

    me = _make_account(session, "+1", project_id=project.id)
    _make_account(
        session, "+2", project_id=project.id,
        username="banned_peer", status="banned",
    )
    _make_account(
        session, "+3", project_id=project.id,
        username="retired_peer", status="retired",
    )

    got = find_trust_peer_username(
        session, me.id, project_id=project.id, persona_id=None, campaign_ids=None
    )
    assert got is None


def test_find_peer_excludes_self(session):
    _clean(session)
    project = Project(user_id="u", name="P")
    session.add(project)
    session.commit()

    me = _make_account(session, "+1", project_id=project.id, username="me")

    got = find_trust_peer_username(
        session, me.id, project_id=project.id, persona_id=None, campaign_ids=None
    )
    assert got is None


def test_find_peer_by_campaign(session):
    _clean(session)
    from datetime import time as t

    campaign = Campaign(
        name="C", target_channel="@ch",
        active_hours_start=t(9, 0), active_hours_end=t(23, 0), active_hours_tz="UTC",
        posting_delay_min_sec=1, posting_delay_max_sec=2,
        base_system_prompt="p", llm_provider="deepseek",
    )
    session.add(campaign)
    session.commit()

    me = _make_account(session, "+1")
    peer = _make_account(session, "+2", username="camp_peer")

    session.add_all([
        CampaignAccount(campaign_id=campaign.id, account_id=me.id),
        CampaignAccount(campaign_id=campaign.id, account_id=peer.id),
    ])
    session.commit()

    got = find_trust_peer_username(
        session, me.id, project_id=None, persona_id=None,
        campaign_ids=[campaign.id],
    )
    assert got == "camp_peer"


def test_collect_campaign_ids_empty_and_present(session):
    _clean(session)
    from datetime import time as t

    me = _make_account(session, "+1")
    assert collect_campaign_ids(session, me.id) == []

    campaign = Campaign(
        name="C", target_channel="@ch",
        active_hours_start=t(9, 0), active_hours_end=t(23, 0), active_hours_tz="UTC",
        posting_delay_min_sec=1, posting_delay_max_sec=2,
        base_system_prompt="p", llm_provider="deepseek",
    )
    session.add(campaign)
    session.commit()
    session.add(CampaignAccount(campaign_id=campaign.id, account_id=me.id))
    session.commit()

    assert collect_campaign_ids(session, me.id) == [campaign.id]


# ── action: interact_with_peer ──────────────────────────────────────────────


class _Ctx:
    def __init__(self, s):
        self._s = s

    def __enter__(self):
        return self._s

    def __exit__(self, *exc):
        return False


async def test_action_no_session_factory_returns_none():
    """Без session_factory action молча возвращает DONE с target=None."""
    from worker.warming.actions.interact_with_peer import execute
    result = await execute(
        client=None,
        account=SimpleNamespace(id=1, project_id=None, persona_id=None),
    )
    assert result.status is WarmingActivityStatus.DONE
    assert result.action_type is WarmingActionType.INTERACT_WITH_PEER
    assert result.target is None


async def test_action_no_peer_returns_done_target_none(session):
    """Есть session_factory, но peer'а нет — DONE с target=None."""
    _clean(session)
    account = _make_account(session, "+1")

    from worker.warming.actions.interact_with_peer import execute

    result = await execute(
        client=None,  # клиент не должен вызываться
        account=account,
        session_factory=lambda: _Ctx(session),
        rng=random.Random(0),
    )
    assert result.status is WarmingActivityStatus.DONE
    assert result.target is None


async def test_action_reads_peer_history(session):
    """Peer найден → client.get_messages(peer, limit=5..15) вызван."""
    _clean(session)
    project = Project(user_id="u", name="P")
    session.add(project)
    session.commit()

    me = _make_account(session, "+1", project_id=project.id)
    _make_account(session, "+2", project_id=project.id, username="mypeer")

    calls: list[dict] = []

    class _Client:
        async def get_messages(self, target, limit):
            calls.append({"target": target, "limit": limit})
            return []  # без сообщений — реакция ставиться не будет

        async def __call__(self, request):
            return None

    from worker.warming.actions.interact_with_peer import execute

    # rng seeded so we know rng.random() > 0.33 → реакции не будет.
    class _NoReactionRng(random.Random):
        def random(self):
            return 0.99

        def randint(self, a, b):
            return 7  # limit = 7

    result = await execute(
        client=_Client(),
        account=me,
        session_factory=lambda: _Ctx(session),
        rng=_NoReactionRng(),
    )
    assert result.status is WarmingActivityStatus.DONE
    assert result.target == "mypeer"
    # Один get_messages вызов с limit=7 (реакция не сработала):
    assert len(calls) == 1
    assert calls[0]["target"] == "mypeer"
    assert calls[0]["limit"] == 7


async def test_action_reacts_with_probability(session):
    """rng.random() < 0.33 → второй get_messages(limit=1) + SendReactionRequest."""
    _clean(session)
    project = Project(user_id="u", name="P")
    session.add(project)
    session.commit()

    me = _make_account(session, "+1", project_id=project.id)
    _make_account(session, "+2", project_id=project.id, username="peer2")

    calls_get_messages: list[dict] = []
    called_requests: list = []

    class _Message:
        id = 42

    class _Client:
        async def get_messages(self, target, limit):
            calls_get_messages.append({"target": target, "limit": limit})
            return [_Message()] if limit == 1 else []

        async def __call__(self, request):
            called_requests.append(request)
            return None

    class _AlwaysReactRng(random.Random):
        def random(self):
            return 0.1  # < 0.33 → реакция

        def randint(self, a, b):
            return 10

    from worker.warming.actions.interact_with_peer import execute

    result = await execute(
        client=_Client(),
        account=me,
        session_factory=lambda: _Ctx(session),
        rng=_AlwaysReactRng(),
    )
    assert result.status is WarmingActivityStatus.DONE
    assert result.target == "peer2"
    # Два get_messages вызова: history (limit=10) + last-1 для реакции:
    assert len(calls_get_messages) == 2
    # SendReactionRequest поставлен:
    from telethon.tl.functions.messages import SendReactionRequest
    assert any(isinstance(r, SendReactionRequest) for r in called_requests)


# ── planner: веса под персон ──────────────────────────────────────────────


def test_planner_registers_interact_with_peer():
    from worker.warming.actions import ACTIONS
    assert WarmingActionType.INTERACT_WITH_PEER in ACTIONS


def test_planner_social_persona_boosts_interact():
    """social-тег даёт вес 2.5 → выбирается чаще базового 1.0."""
    from worker.warming.planner import _compute_weights

    class _P:
        personality_tags = ["social"]

    weights = _compute_weights(_P(), health_score=None)
    action_types = list(WarmingActionType)
    interact_idx = action_types.index(WarmingActionType.INTERACT_WITH_PEER)
    read_idx = action_types.index(WarmingActionType.READ_HISTORY)
    assert weights[interact_idx] > weights[read_idx]
    assert weights[interact_idx] == pytest.approx(2.5)


def test_planner_lurker_persona_downweights_interact():
    from worker.warming.planner import _compute_weights

    class _P:
        personality_tags = ["lurker"]

    weights = _compute_weights(_P(), health_score=None)
    action_types = list(WarmingActionType)
    interact_idx = action_types.index(WarmingActionType.INTERACT_WITH_PEER)
    read_idx = action_types.index(WarmingActionType.READ_HISTORY)
    assert weights[interact_idx] < weights[read_idx]
    assert weights[interact_idx] == pytest.approx(0.3)
