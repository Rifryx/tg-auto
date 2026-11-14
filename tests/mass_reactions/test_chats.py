"""Шаг 4: нормализация источника чатов и решение по подписке."""

from __future__ import annotations

from core.models import MassReactionCampaign
from modules.mass_reactions.chats import (
    normalize_chat_ref,
    parse_chat_list,
    resolve_chat_state,
)
from modules.mass_reactions.repositories import CampaignChatRepository
from modules.mass_reactions.schemas.enums import ChatNotifyMode, ChatState
from modules.mass_reactions.service import add_chats_from_list, apply_resolution


# --- normalize_chat_ref ------------------------------------------------------
def test_normalize_variants():
    assert normalize_chat_ref("@MyChat") == "mychat"
    assert normalize_chat_ref("https://t.me/MyChat") == "mychat"
    assert normalize_chat_ref("t.me/MyChat/42?comment=1") == "mychat"
    assert normalize_chat_ref("-1001234567") == "-1001234567"
    assert normalize_chat_ref("t.me/+AbCdEf") == "t.me/+AbCdEf"
    assert normalize_chat_ref("   ") is None
    assert normalize_chat_ref("") is None


def test_parse_chat_list_dedup_order():
    text = "@a\n@B, a\nt.me/c\n@a"
    assert parse_chat_list(text) == ["a", "b", "c"]


# --- resolve_chat_state ------------------------------------------------------
def test_resolve_chat_state():
    assert resolve_chat_state(subscribed=True, notify_mode="notify_only") == ChatState.ACTIVE.value
    assert resolve_chat_state(subscribed=False, notify_mode="notify_only") == ChatState.NOT_SUBSCRIBED.value
    assert resolve_chat_state(subscribed=False, notify_mode="notify_and_join") == ChatState.JOINING.value
    assert resolve_chat_state(subscribed=True, notify_mode="notify_and_join") == ChatState.ACTIVE.value


# --- DB service --------------------------------------------------------------
def _campaign(session) -> MassReactionCampaign:
    c = MassReactionCampaign(name="mr", reaction_emojis=["👍"])
    session.add(c)
    session.flush()
    return c


def test_add_chats_from_list_dedups_against_existing(session):
    c = _campaign(session)
    first = add_chats_from_list(session, c.id, "@a\n@b", notify_mode="notify_and_join")
    assert [ch.chat_ref for ch in first] == ["a", "b"]
    assert all(ch.notify_mode == "notify_and_join" for ch in first)
    assert all(ch.state == ChatState.PENDING.value for ch in first)

    # Повторно @a (дубль) + новый @c → добавится только @c.
    second = add_chats_from_list(session, c.id, "@a, @c")
    assert [ch.chat_ref for ch in second] == ["c"]
    assert len(CampaignChatRepository(session).list_by_campaign(c.id)) == 3


def test_apply_resolution_sets_state_by_mode(session):
    c = _campaign(session)
    [chat] = add_chats_from_list(
        session, c.id, "@target", notify_mode=ChatNotifyMode.NOTIFY_AND_JOIN.value
    )
    # Не подписан + notify_and_join → joining.
    updated = apply_resolution(
        session, chat.id, chat_tg_id=777, title="Target", subscribed=False
    )
    assert updated.state == ChatState.JOINING.value
    assert updated.chat_tg_id == 777
    assert updated.title == "Target"

    # Если бы был подписан → active.
    [chat2] = add_chats_from_list(session, c.id, "@other", notify_mode="notify_only")
    upd2 = apply_resolution(session, chat2.id, chat_tg_id=1, title=None, subscribed=True)
    assert upd2.state == ChatState.ACTIVE.value
