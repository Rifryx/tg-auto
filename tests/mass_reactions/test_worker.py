"""Шаг 2 масс-реакций: фильтры, выбор эмодзи, классификация ошибок, слушатель."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

from modules.mass_reactions.schemas.enums import ReactionOutcome
from modules.mass_reactions.worker.errors import classify_reaction_error
from modules.mass_reactions.worker.filters import (
    is_live_human,
    is_message_too_old,
    pick_emoji,
    should_react,
)
from modules.mass_reactions.worker.listener import make_chat_message_handler


# --- Telethon-подобные фейки -------------------------------------------------
class User:  # имя класса важно: extract_message_facts проверяет "User"
    def __init__(self, bot=False):
        self.bot = bot


class Msg:
    def __init__(self, *, id=1, sender_id=100, sender=None, out=False, post=False,
                 action=None, date=None):
        self.id = id
        self.sender_id = sender_id
        self.sender = sender if sender is not None else User()
        self.out = out
        self.post = post
        self.action = action
        self.date = date or datetime.now(timezone.utc)


# --- is_live_human -----------------------------------------------------------
def test_live_human_accepts_real_user():
    assert is_live_human(sender_id=100, is_user=True, is_bot=False,
                         is_service=False, is_outgoing=False, own_account_ids=[1, 2])


def test_live_human_rejects_bot_service_self_own_anon():
    base = dict(is_user=True, is_bot=False, is_service=False, is_outgoing=False)
    assert not is_live_human(sender_id=None, **base)                       # аноним/канал
    assert not is_live_human(sender_id=100, **{**base, "is_bot": True})    # бот
    assert not is_live_human(sender_id=100, **{**base, "is_service": True})
    assert not is_live_human(sender_id=100, **{**base, "is_outgoing": True})
    assert not is_live_human(sender_id=100, **{**base, "is_user": False})  # канал-постер
    assert not is_live_human(sender_id=7, own_account_ids=[7, 8], **base)  # свой аккаунт


# --- is_message_too_old ------------------------------------------------------
def test_too_old():
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    recent = now - timedelta(hours=5)
    old = now - timedelta(days=3)
    assert not is_message_too_old(recent, now=now, skip_older_than_days=1)
    assert is_message_too_old(old, now=now, skip_older_than_days=1)
    assert not is_message_too_old(None, now=now, skip_older_than_days=1)


# --- should_react ------------------------------------------------------------
def test_should_react_every_n_and_probability():
    rng = random.Random(0)
    # every_n=3: реагируем только на кратные 3.
    assert not should_react(counter=1, every_n_message=3, probability_percent=100, rng=rng)
    assert not should_react(counter=2, every_n_message=3, probability_percent=100, rng=rng)
    assert should_react(counter=3, every_n_message=3, probability_percent=100, rng=rng)
    # probability=0 → никогда.
    assert not should_react(counter=3, every_n_message=1, probability_percent=0, rng=rng)


# --- pick_emoji --------------------------------------------------------------
def test_pick_emoji_round_robin_and_empty():
    emojis = ["👍", "🔥", "❤️"]
    assert pick_emoji(emojis, strategy="round_robin", counter=1) == "👍"
    assert pick_emoji(emojis, strategy="round_robin", counter=2) == "🔥"
    assert pick_emoji(emojis, strategy="round_robin", counter=4) == "👍"
    assert pick_emoji([], strategy="random") is None


# --- classify_reaction_error -------------------------------------------------
def test_classify_errors():
    class FloodWaitError(Exception):
        seconds = 42

    class PeerFloodError(Exception):
        pass

    class ChatWriteForbiddenError(Exception):
        pass

    class MessageIdInvalidError(Exception):
        pass

    class SomethingElse(Exception):
        pass

    fw = classify_reaction_error(FloodWaitError())
    assert fw.outcome == ReactionOutcome.FLOOD_WAIT and fw.flood_wait_sec == 42
    assert classify_reaction_error(PeerFloodError()).outcome == ReactionOutcome.PEER_FLOOD
    assert classify_reaction_error(ChatWriteForbiddenError()).outcome == ReactionOutcome.FORBIDDEN
    assert classify_reaction_error(MessageIdInvalidError()).outcome == ReactionOutcome.NOT_FOUND
    assert classify_reaction_error(SomethingElse()).outcome == ReactionOutcome.INTERNAL_ERROR


# --- make_chat_message_handler ----------------------------------------------
def _run(coro):
    return asyncio.run(coro)


def test_handler_reacts_on_human_and_counts():
    calls: list[tuple[int, str]] = []
    counter = {"n": 0}

    def inc():
        counter["n"] += 1
        return counter["n"]

    async def enqueue(msg_id, emoji):
        calls.append((msg_id, emoji))

    handler = make_chat_message_handler(
        campaign_id=1, chat_id=1, account_id=5,
        every_n_message=1, probability_percent=100, skip_older_than_days=7,
        emojis=["👍"], increment_counter=inc, enqueue_reaction=enqueue,
        own_account_ids=[5],
    )
    _run(handler(Msg(id=10, sender_id=100)))
    assert calls == [(10, "👍")]
    assert counter["n"] == 1


def test_handler_skips_bot_and_does_not_count():
    calls: list = []
    counter = {"n": 0}

    def inc():
        counter["n"] += 1
        return counter["n"]

    async def enqueue(msg_id, emoji):
        calls.append((msg_id, emoji))

    handler = make_chat_message_handler(
        campaign_id=1, chat_id=1, account_id=5,
        every_n_message=1, probability_percent=100, skip_older_than_days=7,
        emojis=["👍"], increment_counter=inc, enqueue_reaction=enqueue,
    )
    _run(handler(Msg(id=11, sender_id=200, sender=User(bot=True))))
    assert calls == []
    assert counter["n"] == 0  # ботов не считаем


def test_handler_dedup_same_message():
    calls: list = []
    counter = {"n": 0}

    def inc():
        counter["n"] += 1
        return counter["n"]

    async def enqueue(msg_id, emoji):
        calls.append((msg_id, emoji))

    class FakeRedis:
        def __init__(self):
            self.keys = set()

        def set(self, key, val, nx=False, ex=None):
            if key in self.keys:
                return False
            self.keys.add(key)
            return True

    handler = make_chat_message_handler(
        campaign_id=1, chat_id=1, account_id=5,
        every_n_message=1, probability_percent=100, skip_older_than_days=7,
        emojis=["👍"], increment_counter=inc, enqueue_reaction=enqueue,
        redis=FakeRedis(),
    )
    msg = Msg(id=12, sender_id=100)
    _run(handler(msg))
    _run(handler(msg))  # повтор того же сообщения
    assert calls == [(12, "👍")]
    assert counter["n"] == 1
