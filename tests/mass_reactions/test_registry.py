"""Шаг 5c: helpers реестра слушателей (счётчик, enqueue, отбор чатов)."""

from __future__ import annotations

import asyncio
import contextlib

from core.models import Account, MassReactionCampaign
from modules.mass_reactions.repositories import (
    CampaignAccountRepository,
    CampaignChatRepository,
)
from modules.mass_reactions.schemas.enums import (
    ChatState,
    MassReactionCampaignStatus,
)
from modules.mass_reactions.worker.registry import (
    _listenable,
    make_counter,
    make_enqueue,
)


def _factory(session):
    @contextlib.contextmanager
    def f():
        yield session
    return f


def _account(session, n):
    a = Account(
        phone=f"+79000{n:05d}", session_enc=b"e", status="assigned",
        device_model="iPhone15,3", system_version="17", app_version="10",
        lang_code="uk", system_lang_code="uk-UA",
    )
    session.add(a)
    session.flush()
    return a


def test_make_counter_bumps_persistently(session):
    c = MassReactionCampaign(name="mr", reaction_emojis=["👍"])
    session.add(c)
    session.flush()
    chat = CampaignChatRepository(session).create({"campaign_id": c.id, "chat_ref": "@a"})
    inc = make_counter(_factory(session), chat.id)
    assert inc() == 1
    assert inc() == 2
    session.refresh(chat)
    assert chat.reaction_counter == 2


def test_make_enqueue_puts_place_reaction():
    calls = []

    class Q:
        async def enqueue(self, name, *args):
            calls.append((getattr(name, "value", name), args))

    enq = make_enqueue(Q(), campaign_id=1, chat_id=2, account_id=3, chat_tg_id=999, dry_run=False)
    asyncio.run(enq(55, "🔥"))
    assert calls == [("mass_reactions.place_reaction", (1, 2, 3, 999, 55, "🔥", False))]


def test_listenable_selects_running_active_resolved(session):
    # running + active + resolved + assigned → попадает
    c = MassReactionCampaign(
        name="mr", reaction_emojis=["👍"],
        status=MassReactionCampaignStatus.RUNNING.value,
    )
    session.add(c)
    session.flush()
    a = _account(session, 1)
    CampaignAccountRepository(session).create({"campaign_id": c.id, "account_id": a.id})
    chats = CampaignChatRepository(session)
    good = chats.create({
        "campaign_id": c.id, "chat_ref": "@good", "account_id": a.id,
        "chat_tg_id": 12345, "state": ChatState.ACTIVE.value,
    })
    # pending без резолва — не слушаем
    chats.create({"campaign_id": c.id, "chat_ref": "@pending"})
    session.flush()

    specs = _listenable(_factory(session))
    ids = [s["chat_id"] for s in specs]
    assert ids == [good.id]
    assert specs[0]["chat_tg_id"] == 12345
    assert specs[0]["every_n_message"] == c.every_n_message


def test_listenable_skips_paused_campaign(session):
    c = MassReactionCampaign(
        name="mr", reaction_emojis=["👍"],
        status=MassReactionCampaignStatus.PAUSED.value,
    )
    session.add(c)
    session.flush()
    a = _account(session, 2)
    CampaignChatRepository(session).create({
        "campaign_id": c.id, "chat_ref": "@x", "account_id": a.id,
        "chat_tg_id": 1, "state": ChatState.ACTIVE.value,
    })
    session.flush()
    assert _listenable(_factory(session)) == []
