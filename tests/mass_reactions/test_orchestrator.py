"""Шаг 3: раскладчик чат/аккаунт, репозитории, executor реакции."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone

from core.models import Account, MassReactionCampaign
from modules.mass_reactions.repositories import (
    CampaignAccountRepository,
    CampaignChatRepository,
    LogRepository,
)
from modules.mass_reactions.schemas.enums import ChatState, ReactionOutcome
from modules.mass_reactions.worker.executor import place_reaction
from modules.mass_reactions.worker.orchestrator import (
    assign_pending_chats,
    plan_chat_assignments,
)


# --- pure planner ------------------------------------------------------------
def test_plan_balances_and_respects_slots():
    # 3 аккаунта по 2 слота, 5 чатов → 5 назначено (баланс), один слот свободен.
    plan = plan_chat_assignments([1, 2, 3, 4, 5], [(10, 2), (20, 2), (30, 2)])
    assert len(plan) == 5
    per_acc = {}
    for _chat, acc in plan:
        per_acc[acc] = per_acc.get(acc, 0) + 1
    assert all(v <= 2 for v in per_acc.values())


def test_plan_overflow_left_unassigned():
    # 2 слота всего, 5 чатов → только 2 назначены.
    plan = plan_chat_assignments([1, 2, 3, 4, 5], [(10, 1), (20, 1), (30, 0)])
    assert len(plan) == 2


# --- helpers -----------------------------------------------------------------
def _account(session, n: int) -> Account:
    acc = Account(
        phone=f"+79000{n:05d}",
        session_enc=b"enc",
        status="assigned",
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    session.add(acc)
    session.flush()
    return acc


def _campaign(session, **over) -> MassReactionCampaign:
    data = dict(name="mr", reaction_emojis=["👍"], max_chats_per_account=2)
    data.update(over)
    c = MassReactionCampaign(**data)
    session.add(c)
    session.flush()
    return c


# --- repositories ------------------------------------------------------------
def test_chat_bump_counter_atomic(session):
    c = _campaign(session)
    chats = CampaignChatRepository(session)
    chat = chats.create({"campaign_id": c.id, "chat_ref": "@a"})
    assert chats.bump_counter(chat.id) == 1
    assert chats.bump_counter(chat.id) == 2
    assert chats.bump_counter(chat.id) == 3


def test_assign_pending_chats_respects_cap(session):
    c = _campaign(session, max_chats_per_account=2)
    a1 = _account(session, 1)
    accounts = CampaignAccountRepository(session)
    accounts.create({"campaign_id": c.id, "account_id": a1.id})
    chats = CampaignChatRepository(session)
    for i in range(3):
        chats.create({"campaign_id": c.id, "chat_ref": f"@c{i}"})

    assigned = assign_pending_chats(session, c)
    # Один аккаунт, cap=2 → назначено 2, третий чат ждёт.
    assert assigned == 2
    counts = chats.count_by_account(c.id)
    assert counts.get(a1.id) == 2


# --- executor ----------------------------------------------------------------
def _factory(session):
    @contextlib.contextmanager
    def f():
        yield session
    return f


def test_place_reaction_success_logs_and_counts(session):
    c = _campaign(session)
    a = _account(session, 2)
    accounts = CampaignAccountRepository(session)
    acc_link = accounts.create({"campaign_id": c.id, "account_id": a.id})
    chat = CampaignChatRepository(session).create(
        {"campaign_id": c.id, "chat_ref": "@t", "account_id": a.id}
    )

    sent: list = []

    async def send(chat_tg_id, msg_id, emoji):
        sent.append((chat_tg_id, msg_id, emoji))

    outcome = asyncio.run(
        place_reaction(
            session_factory=_factory(session),
            send=send,
            campaign_id=c.id,
            chat_id=chat.id,
            account_id=a.id,
            chat_tg_id=12345,
            msg_id=99,
            emoji="👍",
        )
    )
    assert outcome == ReactionOutcome.REACTED
    assert sent == [(12345, 99, "👍")]
    assert LogRepository(session).count_by_outcome(c.id) == {"reacted": 1}
    session.refresh(acc_link)
    assert acc_link.reactions_total == 1
    session.refresh(chat)
    assert chat.reactions_total == 1


def test_place_reaction_flood_wait_logs_error_no_count(session):
    c = _campaign(session)
    a = _account(session, 3)
    acc_link = CampaignAccountRepository(session).create(
        {"campaign_id": c.id, "account_id": a.id}
    )
    chat = CampaignChatRepository(session).create(
        {"campaign_id": c.id, "chat_ref": "@t2", "account_id": a.id}
    )

    class FloodWaitError(Exception):
        seconds = 30

    async def send(chat_tg_id, msg_id, emoji):
        raise FloodWaitError()

    outcome = asyncio.run(
        place_reaction(
            session_factory=_factory(session),
            send=send,
            campaign_id=c.id,
            chat_id=chat.id,
            account_id=a.id,
            chat_tg_id=1,
            msg_id=5,
            emoji="🔥",
        )
    )
    assert outcome == ReactionOutcome.FLOOD_WAIT
    assert LogRepository(session).count_by_outcome(c.id) == {"flood_wait": 1}
    session.refresh(acc_link)
    assert acc_link.reactions_total == 0  # неуспех не инкрементит счётчик
