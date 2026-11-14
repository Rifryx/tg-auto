"""Шаг 1 модуля масс-реакций: схема + модели создаются и констрейнты работают."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from core.models import (
    MassReactionCampaign,
    MassReactionCampaignChat,
)
from modules.mass_reactions.schemas.enums import (
    ChatNotifyMode,
    ChatState,
    MassReactionCampaignStatus,
)


def _campaign(**over) -> MassReactionCampaign:
    data = dict(name="c1", reaction_emojis=["👍", "🔥"])
    data.update(over)
    return MassReactionCampaign(**data)


def test_campaign_defaults(session):
    c = _campaign()
    session.add(c)
    session.commit()

    assert c.id is not None
    # Серверные дефолты подхватились.
    assert c.status == MassReactionCampaignStatus.DRAFT.value
    assert c.chat_source_mode == "by_subscriptions"
    assert c.reaction_strategy == "random"
    assert c.every_n_message == 1
    assert c.probability_percent == 100
    assert c.first_n_in_burst == 3
    assert c.duration_hours == 24
    assert c.daily_limit_per_account == 200
    assert c.max_chats_per_account == 5
    assert c.warmup_profile == "warm"
    assert c.humanizer_mode == "balanced"
    assert c.meta == {}


def test_empty_emojis_rejected(session):
    session.add(_campaign(reaction_emojis=[]))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_probability_out_of_range_rejected(session):
    session.add(_campaign(probability_percent=0))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_chat_binding_and_counter(session):
    c = _campaign()
    session.add(c)
    session.flush()

    chat = MassReactionCampaignChat(
        campaign_id=c.id,
        chat_ref="@target_chat",
        notify_mode=ChatNotifyMode.NOTIFY_AND_JOIN.value,
    )
    session.add(chat)
    session.commit()

    assert chat.id is not None
    assert chat.state == ChatState.PENDING.value
    assert chat.account_id is None  # закрепление назначит tick
    assert chat.reaction_counter == 0


def test_duplicate_chat_ref_in_campaign_rejected(session):
    c = _campaign()
    session.add(c)
    session.flush()
    session.add_all(
        [
            MassReactionCampaignChat(campaign_id=c.id, chat_ref="@dup"),
            MassReactionCampaignChat(campaign_id=c.id, chat_ref="@dup"),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
