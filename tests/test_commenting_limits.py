"""Лимиты работы кампании (E2.2): max_comments, min_words, окно после поста,
пауза между комментами. БД настоящая, Telethon/LLM — фейки."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.enums import CommentStatus
from core.queue.task_names import TaskName
from core.models import CampaignAccount
from modules.commenting.repositories import CampaignRepository, CommentLogRepository
from modules.commenting.schemas import CommentLogCreate
from modules.commenting.worker import limits, listener, runner
from tests.test_commenting_worker import (
    NOW_INSIDE,
    _clean,
    _ctx,
    _FakeGovernor,
    _make_assigned,
    _make_campaign,
    _Rng,
    _SpyTaskQueue,
)

pytestmark = pytest.mark.asyncio


class _ScriptedLLM:
    """Отдаёт тексты по очереди (последний повторяется), считает вызовы."""

    def __init__(self, *texts: str):
        self.texts = list(texts)
        self.calls = 0

    async def generate(self, system, messages, max_tokens=200, temperature=0.8):
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return text


class _PlainStyle:
    def randomize(self, text, persona):
        return text


def _set(session, campaign_id, **fields):
    c = CampaignRepository(session).get(campaign_id)
    for k, v in fields.items():
        setattr(c, k, v)
    session.commit()


def _posted(session, campaign_id, account_id, n=1):
    for i in range(n):
        CommentLogRepository(session).create(
            CommentLogCreate(
                campaign_id=campaign_id, account_id=account_id, post_channel_msg_id=1,
                comment_text=f"c{i}", status=CommentStatus.POSTED, posted_message_id=i + 1,
            )
        )
    session.commit()


def _ctx_llm(session, spy, llm, *, client=None, now=NOW_INSIDE):
    ctx = _ctx(session, now=now, rng=_Rng(random_value=0.9), task_queue=spy,
               client=client, governor=_FakeGovernor())
    ctx["llm_provider"] = llm
    ctx["style_randomizer"] = _PlainStyle()
    return ctx


# ── чистые функции ──────────────────────────────────────────────────────────


async def test_word_count_ignores_emoji_and_punctuation():
    assert limits.word_count("Привет, как дела? 👍 !!!") == 3
    assert limits.word_count("") == 0


async def test_window_only_in_time_window_mode():
    now = NOW_INSIDE
    old = now - timedelta(hours=2)
    by_count = SimpleNamespace(work_mode="by_count", window_after_post_sec=60)
    by_time = SimpleNamespace(work_mode="by_time_window", window_after_post_sec=3600)
    assert limits.window_closed(by_count, old, now) is False
    assert limits.window_closed(by_time, old, now) is True
    assert limits.window_closed(by_time, now - timedelta(minutes=10), now) is False
    assert limits.window_closed(by_time, None, now) is False  # без даты не блокируем


# ── max_comments ────────────────────────────────────────────────────────────


async def test_max_comments_stops_planning_and_sending(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_assigned(session, campaign_id)
    _make_assigned(session, campaign_id)
    _set(session, campaign_id, max_comments=2)
    _posted(session, campaign_id, account_id, n=2)

    spy = _SpyTaskQueue()
    assert await runner.on_new_post(_ctx_llm(session, spy, _ScriptedLLM("a b c")), campaign_id, 100) == 0
    assert spy.scheduled == []

    client = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=9)))
    res = await runner.post_comment(
        _ctx_llm(session, spy, _ScriptedLLM("x"), client=client), campaign_id, account_id, "hi", 100, 100
    )
    assert res is None
    client.send_message.assert_not_awaited()


async def test_failed_attempts_do_not_eat_the_limit(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_assigned(session, campaign_id)
    _set(session, campaign_id, max_comments=1)
    CommentLogRepository(session).create(
        CommentLogCreate(campaign_id=campaign_id, account_id=account_id, post_channel_msg_id=1,
                         comment_text="x", status=CommentStatus.FAILED, error="boom")
    )
    session.commit()

    spy = _SpyTaskQueue()
    assert await runner.on_new_post(_ctx_llm(session, spy, _ScriptedLLM("ok")), campaign_id, 100) == 1


# ── min_words ───────────────────────────────────────────────────────────────


async def test_min_words_retries_until_long_enough(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _make_assigned(session, campaign_id)
    _set(session, campaign_id, min_words=4)
    llm = _ScriptedLLM("коротко", "всё ещё мало", "вот теперь нормальный длинный ответ")

    spy = _SpyTaskQueue()
    assert await runner.on_new_post(_ctx_llm(session, spy, llm), campaign_id, 100) == 1
    assert llm.calls == 3
    assert spy.scheduled[0][2][2] == "вот теперь нормальный длинный ответ"


async def test_min_words_gives_up_and_logs_failed(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_assigned(session, campaign_id)
    _set(session, campaign_id, min_words=10)
    llm = _ScriptedLLM("мало слов")

    spy = _SpyTaskQueue()
    assert await runner.on_new_post(_ctx_llm(session, spy, llm), campaign_id, 100) == 0
    assert llm.calls == limits.MIN_WORDS_ATTEMPTS
    assert spy.scheduled == []
    logs = CommentLogRepository(session).list_by_campaign(campaign_id)
    assert [(l.account_id, l.status, l.error) for l in logs] == [
        (account_id, "failed", "below_min_words:10")
    ]


# ── окно после поста ────────────────────────────────────────────────────────


async def test_time_window_skips_old_posts_and_carries_post_date(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _make_assigned(session, campaign_id)
    _set(session, campaign_id, work_mode="by_time_window", window_after_post_sec=600)

    spy = _SpyTaskQueue()
    old_ts = (NOW_INSIDE - timedelta(minutes=20)).timestamp()
    assert await runner.on_new_post(
        _ctx_llm(session, spy, _ScriptedLLM("ok")), campaign_id, 100, post_date_ts=old_ts
    ) == 0

    fresh_ts = (NOW_INSIDE - timedelta(minutes=5)).timestamp()
    assert await runner.on_new_post(
        _ctx_llm(session, spy, _ScriptedLLM("ok")), campaign_id, 100, post_date_ts=fresh_ts
    ) == 1
    # дата поста едет дальше в post_comment — окно перепроверится при отправке
    assert spy.scheduled[0][3]["post_date_ts"] == fresh_ts


async def test_window_rechecked_at_send_time(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_assigned(session, campaign_id)
    _set(session, campaign_id, work_mode="by_time_window", window_after_post_sec=600)
    client = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=9)))

    spy = _SpyTaskQueue()
    ts = (NOW_INSIDE - timedelta(minutes=11)).timestamp()  # спланировали в окне, отправка — уже нет
    res = await runner.post_comment(
        _ctx_llm(session, spy, _ScriptedLLM("x"), client=client),
        campaign_id, account_id, "hi", 100, 100, post_date_ts=ts,
    )
    assert res is None
    client.send_message.assert_not_awaited()


# ── пауза между комментами ──────────────────────────────────────────────────


async def test_pause_reschedules_then_stamps_after_send(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_assigned(session, campaign_id)
    _set(session, campaign_id, work_mode="by_time_window", pause_between_sec=120)
    link = session.get(CampaignAccount, (campaign_id, account_id))
    link.last_posted_at = NOW_INSIDE - timedelta(seconds=30)
    session.commit()
    client = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=9)))

    spy = _SpyTaskQueue()
    res = await runner.post_comment(
        _ctx_llm(session, spy, _ScriptedLLM("x"), client=client), campaign_id, account_id, "hi", 100, 100
    )
    assert res is None
    client.send_message.assert_not_awaited()
    name, run_at, args, _ = spy.scheduled[0]
    assert name == TaskName.COMMENTING_POST_COMMENT
    assert run_at == NOW_INSIDE + timedelta(seconds=90)

    # пауза прошла → отправляет и ставит last_posted_at = now
    later = NOW_INSIDE + timedelta(seconds=90)
    res = await runner.post_comment(
        _ctx_llm(session, _SpyTaskQueue(), _ScriptedLLM("x"), client=client, now=later),
        campaign_id, account_id, "hi", 100, 100,
    )
    assert res == 9
    session.refresh(link)
    assert link.last_posted_at == later


async def test_pause_ignored_in_count_mode(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_assigned(session, campaign_id)
    _set(session, campaign_id, work_mode="by_count", pause_between_sec=120)
    link = session.get(CampaignAccount, (campaign_id, account_id))
    link.last_posted_at = NOW_INSIDE - timedelta(seconds=5)
    session.commit()
    client = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=9)))

    res = await runner.post_comment(
        _ctx_llm(session, _SpyTaskQueue(), _ScriptedLLM("x"), client=client),
        campaign_id, account_id, "hi", 100, 100,
    )
    assert res == 9


# ── слушатель передаёт дату публикации ──────────────────────────────────────


async def test_listener_passes_post_date():
    spy = _SpyTaskQueue()
    handler = listener.make_new_post_handler(1, spy, channel_id=777)
    date = datetime(2026, 9, 12, 11, 30, tzinfo=timezone.utc)
    await handler(SimpleNamespace(message=SimpleNamespace(sender_id=777, id=5, date=date)))
    assert spy.enqueued == [
        (TaskName.COMMENTING_ON_NEW_POST, (1, 5), {"post_date_ts": date.timestamp()})
    ]
