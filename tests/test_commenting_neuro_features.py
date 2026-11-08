"""Тесты «доп. режимов нейрокомментинга» (как у конкурента):

* экономия токенов (стаб-пробник → ИИ-замена/провал без LLM-вызова);
* отложенный запуск кампании (scheduled_start_at);
* упоминание продукта в system-промпте;
* пересылка готовых постов из @PostBot вместо ИИ;
* решение капчи (текст/кнопки, кэш «один пробник на группу»).

БД настоящая для интеграционных сценариев (post_comment); чистый unit — на
SimpleNamespace/фейковых Telethon-клиентах, как в остальных commenting-тестах.
"""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from core.enums import CommentStatus
from modules.commenting.repositories import CampaignRepository, CommentLogRepository
from modules.commenting.worker import captcha, delivery, runner
from tests.test_commenting_channels import (
    _ctx as _base_ctx,
    _make_account,
    _make_campaign,
    _SpyPublisher,
    _SpyTaskQueue,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
_TABLES = (
    "accounts",
    "health_events",
    "account_status_history",
    '"commenting".campaigns',
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
    '"commenting".monitored_channels',
)


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _set(session, campaign_id, **fields):
    c = CampaignRepository(session).get(campaign_id)
    for k, v in fields.items():
        setattr(c, k, v)
    session.commit()


class _StaticStyle:
    """StyleRandomizer-заглушка: текст проходит без искажений (для точных
    ассертов на итоговый comment_text в интеграционных тестах economy)."""

    def randomize(self, text_, persona):
        return text_


def _ctx(session, client, *, rng=None, publisher=None, redis_sync=None):
    ctx = _base_ctx(session, client=client, task_queue=_SpyTaskQueue(), publisher=publisher)
    ctx["rng"] = rng or random.Random(0)
    ctx["redis_sync"] = redis_sync
    ctx["style_randomizer"] = _StaticStyle()
    return ctx


# ── stub_text ──────────────────────────────────────────────────────────────


def test_stub_text_is_short_and_deterministic_with_seeded_rng():
    s1 = delivery.stub_text(random.Random(1))
    s2 = delivery.stub_text(random.Random(1))
    assert s1 == s2
    parts = s1.split(" ")
    assert len(parts) == delivery._ECONOMY_STUB_DIGITS
    assert all(p.isdigit() for p in parts)


# ── deliver_economy ──────────────────────────────────────────────────────────


class _EconomyClient:
    def __init__(self, *, still_there: bool, edit_fails: bool = False):
        self.send_message = AsyncMock(return_value=SimpleNamespace(id=42))
        self.get_messages = AsyncMock(
            return_value=[SimpleNamespace(id=42)] if still_there else [None]
        )
        if edit_fails:
            self.edit_message = AsyncMock(side_effect=RuntimeError("edit blocked"))
        else:
            self.edit_message = AsyncMock(return_value=None)


async def test_deliver_economy_passes_and_replaces_with_real_text(monkeypatch):
    monkeypatch.setattr(delivery.asyncio, "sleep", AsyncMock(return_value=None))
    client = _EconomyClient(still_there=True)
    campaign = SimpleNamespace()
    calls = {"n": 0}

    async def generate_real():
        calls["n"] += 1
        return "настоящий ИИ-коммент"

    sent, mode, final_text = await delivery.deliver_economy(
        {"session_factory": lambda: None},
        client, campaign,
        account_id=1, discussion_group_id=555, reply_to=100,
        now=NOW, publisher=None, rng=random.Random(0),
        generate_real=generate_real,
    )
    assert mode == "economy_passed"
    assert final_text == "настоящий ИИ-коммент"
    assert calls["n"] == 1
    client.edit_message.assert_awaited_once()
    assert client.edit_message.await_args.args[2] == "настоящий ИИ-коммент"


async def test_deliver_economy_fails_probe_never_calls_llm(monkeypatch):
    monkeypatch.setattr(delivery.asyncio, "sleep", AsyncMock(return_value=None))
    client = _EconomyClient(still_there=False)
    campaign = SimpleNamespace()
    calls = {"n": 0}

    async def generate_real():
        calls["n"] += 1
        return "should never be called"

    sent, mode, final_text = await delivery.deliver_economy(
        {"session_factory": lambda: None},
        client, campaign,
        account_id=1, discussion_group_id=555, reply_to=100,
        now=NOW, publisher=None, rng=random.Random(0),
        generate_real=generate_real,
    )
    assert mode == "economy_failed"
    assert calls["n"] == 0  # экономия: ИИ не вызывался
    client.edit_message.assert_not_called()


async def test_deliver_economy_edit_failure_keeps_stub(monkeypatch):
    monkeypatch.setattr(delivery.asyncio, "sleep", AsyncMock(return_value=None))
    client = _EconomyClient(still_there=True, edit_fails=True)
    campaign = SimpleNamespace()

    async def generate_real():
        return "real text"

    sent, mode, final_text = await delivery.deliver_economy(
        {"session_factory": lambda: None},
        client, campaign,
        account_id=1, discussion_group_id=555, reply_to=100,
        now=NOW, publisher=None, rng=random.Random(0),
        generate_real=generate_real,
    )
    assert mode == "economy_edit_failed"
    # final_text — заглушка (её мы и не смогли заменить), не "real text".
    assert final_text != "real text"


# ── deliver_postbot ──────────────────────────────────────────────────────────


class _PostbotClient:
    def __init__(self, *, source=None):
        self._source = source
        self.send_message = AsyncMock(return_value=SimpleNamespace(id=1))
        self.send_file = AsyncMock(return_value=SimpleNamespace(id=2))
        self.get_messages = AsyncMock(return_value=[self._source] if self._source else [None])


async def test_deliver_postbot_text_only_copies_via_send_message():
    source = SimpleNamespace(id=10, text="готовый текст поста", message="готовый текст поста", media=None)
    client = _PostbotClient(source=source)
    campaign = SimpleNamespace(postbot_message_ids=[10], postbot_username=None)
    sent, mode, picked = await delivery.deliver_postbot(
        {"session_factory": lambda: None},
        client, campaign,
        account_id=1, discussion_group_id=555, reply_to=100,
        now=NOW, publisher=None, rng=random.Random(0),
    )
    assert mode == "postbot"
    assert picked == 10
    client.send_message.assert_awaited_once()
    assert client.send_message.await_args.args[1] == "готовый текст поста"
    client.send_file.assert_not_called()


async def test_deliver_postbot_with_media_uses_send_file():
    source = SimpleNamespace(id=11, text="caption", message="caption", media=object())
    client = _PostbotClient(source=source)
    campaign = SimpleNamespace(postbot_message_ids=[11], postbot_username="MyPostBot")
    sent, mode, picked = await delivery.deliver_postbot(
        {"session_factory": lambda: None},
        client, campaign,
        account_id=1, discussion_group_id=555, reply_to=100,
        now=NOW, publisher=None, rng=random.Random(0),
    )
    assert picked == 11
    client.send_file.assert_awaited_once()
    assert client.send_file.await_args.kwargs["caption"] == "caption"


async def test_deliver_postbot_missing_message_raises():
    client = _PostbotClient(source=None)
    campaign = SimpleNamespace(postbot_message_ids=[999], postbot_username=None)
    with pytest.raises(ValueError):
        await delivery.deliver_postbot(
            {"session_factory": lambda: None},
            client, campaign,
            account_id=1, discussion_group_id=555, reply_to=100,
            now=NOW, publisher=None, rng=random.Random(0),
        )


async def test_deliver_postbot_empty_pool_raises():
    campaign = SimpleNamespace(postbot_message_ids=[], postbot_username=None)
    with pytest.raises(ValueError):
        await delivery.deliver_postbot(
            {"session_factory": lambda: None},
            _PostbotClient(), campaign,
            account_id=1, discussion_group_id=555, reply_to=100,
            now=NOW, publisher=None, rng=random.Random(0),
        )


# ── _scheduled_not_yet / отложенный запуск ───────────────────────────────────


def test_scheduled_not_yet_none_means_no_delay():
    campaign = SimpleNamespace(scheduled_start_at=None)
    assert runner._scheduled_not_yet(campaign, NOW) is False


def test_scheduled_not_yet_future_blocks():
    campaign = SimpleNamespace(scheduled_start_at=NOW + timedelta(hours=1))
    assert runner._scheduled_not_yet(campaign, NOW) is True


def test_scheduled_not_yet_past_allows():
    campaign = SimpleNamespace(scheduled_start_at=NOW - timedelta(hours=1))
    assert runner._scheduled_not_yet(campaign, NOW) is False


def test_scheduled_not_yet_handles_naive_datetime():
    campaign = SimpleNamespace(scheduled_start_at=(NOW + timedelta(hours=1)).replace(tzinfo=None))
    assert runner._scheduled_not_yet(campaign, NOW) is True


# ── _skip_llm_mode: postbot важнее economy ───────────────────────────────────


def test_skip_llm_mode_normal_when_both_off():
    campaign = SimpleNamespace(
        postbot_forward_enabled=False, postbot_message_ids=[],
        token_economy_enabled=False,
    )
    assert runner._skip_llm_mode(campaign) == "normal"


def test_skip_llm_mode_economy_when_only_economy_on():
    campaign = SimpleNamespace(
        postbot_forward_enabled=False, postbot_message_ids=[],
        token_economy_enabled=True,
    )
    assert runner._skip_llm_mode(campaign) == "economy"


def test_skip_llm_mode_postbot_wins_over_economy():
    campaign = SimpleNamespace(
        postbot_forward_enabled=True, postbot_message_ids=[1, 2],
        token_economy_enabled=True,
    )
    assert runner._skip_llm_mode(campaign) == "postbot"


def test_skip_llm_mode_postbot_ignored_when_pool_empty():
    campaign = SimpleNamespace(
        postbot_forward_enabled=True, postbot_message_ids=[],
        token_economy_enabled=True,
    )
    assert runner._skip_llm_mode(campaign) == "economy"


# ── упоминание продукта ──────────────────────────────────────────────────────


def test_product_mention_suffix_empty_when_disabled():
    campaign = SimpleNamespace(product_mention_enabled=False, product_name="X")
    assert runner._product_mention_suffix(campaign, random.Random(0)) == ""


def test_product_mention_suffix_empty_without_name():
    campaign = SimpleNamespace(
        product_mention_enabled=True, product_name=None, product_mention_chance_percent=100,
    )
    assert runner._product_mention_suffix(campaign, random.Random(0)) == ""


def test_product_mention_suffix_included_at_full_chance():
    campaign = SimpleNamespace(
        product_mention_enabled=True, product_name="АкмеКрем",
        product_mention_chance_percent=100, product_url="https://acme.example",
    )
    out = runner._product_mention_suffix(campaign, random.Random(0))
    assert "АкмеКрем" in out
    assert "https://acme.example" in out


def test_product_mention_suffix_excluded_at_zero_chance():
    campaign = SimpleNamespace(
        product_mention_enabled=True, product_name="АкмеКрем",
        product_mention_chance_percent=0, product_url=None,
    )
    assert runner._product_mention_suffix(campaign, random.Random(0)) == ""


# ── капча: эвристика + решение ───────────────────────────────────────────────


def test_looks_like_captcha_detects_keyword():
    assert captcha._looks_like_captcha(SimpleNamespace(message="Пройдите капчу, нажмите кнопку", buttons=None))


def test_looks_like_captcha_detects_arithmetic():
    assert captcha._looks_like_captcha(SimpleNamespace(message="Сколько будет 3 + 5?", buttons=None))


def test_looks_like_captcha_detects_buttons():
    assert captcha._looks_like_captcha(SimpleNamespace(message="Добро пожаловать", buttons=[["x"]]))


def test_looks_like_captcha_false_for_plain_message():
    assert not captcha._looks_like_captcha(SimpleNamespace(message="Привет всем, как дела?", buttons=None))


class _CaptchaClient:
    def __init__(self, messages):
        self._messages = messages
        self.get_messages = AsyncMock(return_value=messages)
        self.send_message = AsyncMock(return_value=SimpleNamespace(id=1))


class _CaptchaLLM:
    def __init__(self, answer):
        self.answer = answer

    async def generate(self, system, messages, max_tokens=30, temperature=0.0):
        return self.answer


def _bot_msg(id_, text_, *, buttons=None, bot=True, dt=NOW):
    return SimpleNamespace(
        id=id_, message=text_, buttons=buttons, date=dt,
        sender=SimpleNamespace(bot=bot),
        click=AsyncMock(return_value=None),
    )


async def test_maybe_solve_captcha_answers_text_challenge_and_caches():
    msg = _bot_msg(5, "Сколько будет 2 + 2? Ответьте числом.")
    client = _CaptchaClient([msg])
    redis = {}
    ctx = {"session_factory": lambda: None, "redis_sync": _FakeSyncRedis(redis)}
    await captcha.maybe_solve_captcha(
        ctx, client, account_id=1, discussion_group_id=555,
        provider=_CaptchaLLM("4"), publisher=None, now=NOW,
    )
    client.send_message.assert_awaited_once()
    assert client.send_message.await_args.args[1] == "4"
    assert client.send_message.await_args.kwargs["reply_to"] == 5
    # Кэш выставлен — повторный вызов больше не должен ничего слать.
    client.send_message.reset_mock()
    await captcha.maybe_solve_captcha(
        ctx, client, account_id=1, discussion_group_id=555,
        provider=_CaptchaLLM("4"), publisher=None, now=NOW,
    )
    client.send_message.assert_not_called()


async def test_maybe_solve_captcha_clicks_matching_button():
    btn = SimpleNamespace(text="Я не бот")
    msg = _bot_msg(6, "Нажмите кнопку ниже, чтобы подтвердить, что вы не бот", buttons=[[btn]])
    client = _CaptchaClient([msg])
    ctx = {"session_factory": lambda: None, "redis_sync": _FakeSyncRedis({})}
    await captcha.maybe_solve_captcha(
        ctx, client, account_id=1, discussion_group_id=555,
        provider=_CaptchaLLM("Я не бот"), publisher=None, now=NOW,
    )
    msg.click.assert_awaited_once_with(text="Я не бот")


async def test_maybe_solve_captcha_does_not_click_on_unmatched_answer():
    btn = SimpleNamespace(text="Verify")
    msg = _bot_msg(7, "Press the button to verify", buttons=[[btn]])
    client = _CaptchaClient([msg])
    ctx = {"session_factory": lambda: None, "redis_sync": _FakeSyncRedis({})}
    await captcha.maybe_solve_captcha(
        ctx, client, account_id=1, discussion_group_id=555,
        provider=_CaptchaLLM("Something else entirely"), publisher=None, now=NOW,
    )
    msg.click.assert_not_called()


async def test_maybe_solve_captcha_skips_non_bot_messages():
    msg = _bot_msg(8, "Сколько будет 2 + 2?", bot=False)
    client = _CaptchaClient([msg])
    ctx = {"session_factory": lambda: None, "redis_sync": _FakeSyncRedis({})}
    await captcha.maybe_solve_captcha(
        ctx, client, account_id=1, discussion_group_id=555,
        provider=_CaptchaLLM("4"), publisher=None, now=NOW,
    )
    client.send_message.assert_not_called()


async def test_maybe_solve_captcha_skips_stale_challenge():
    old = NOW - timedelta(minutes=30)
    msg = _bot_msg(9, "Сколько будет 2 + 2?", dt=old)
    client = _CaptchaClient([msg])
    ctx = {"session_factory": lambda: None, "redis_sync": _FakeSyncRedis({})}
    await captcha.maybe_solve_captcha(
        ctx, client, account_id=1, discussion_group_id=555,
        provider=_CaptchaLLM("4"), publisher=None, now=NOW,
    )
    client.send_message.assert_not_called()


class _FakeSyncRedis:
    """Минимальный синхронный redis-like стаб для кэша капчи (get/set)."""

    def __init__(self, store: dict):
        self._store = store

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value, ex=None):
        self._store[key] = value


# ── post_comment: интеграция economy/postbot (БД настоящая) ─────────────────


async def test_post_comment_economy_probe_failed_logs_failed_without_llm(session, monkeypatch):
    _clean(session)
    monkeypatch.setattr(delivery.asyncio, "sleep", AsyncMock(return_value=None))
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, token_economy_enabled=True, discussion_group_id=555)
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)

    client = _EconomyClient(still_there=False)
    pub = _SpyPublisher()
    ctx = _ctx(session, client, publisher=pub)

    posted = await runner.post_comment(
        ctx, campaign_id, account_id, "", 100, 100,
        economy_stub=True,
    )
    assert posted is None
    logs = CommentLogRepository(session).list_by_campaign(campaign_id)
    assert len(logs) == 1
    assert logs[0].status == CommentStatus.FAILED.value
    assert logs[0].error == "economy_probe_failed"
    assert logs[0].is_economy_stub is True


async def test_post_comment_economy_probe_passed_logs_posted_with_real_text(session, monkeypatch):
    _clean(session)
    monkeypatch.setattr(delivery.asyncio, "sleep", AsyncMock(return_value=None))
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, token_economy_enabled=True, discussion_group_id=555)
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)

    client = _EconomyClient(still_there=True)
    ctx = _ctx(session, client)
    ctx["llm_provider"] = _CaptchaLLM("сгенерированный коммент")

    posted = await runner.post_comment(
        ctx, campaign_id, account_id, "", 100, 100,
        economy_stub=True, post_text="пост канала",
    )
    assert posted == 42
    logs = CommentLogRepository(session).list_by_campaign(campaign_id)
    assert len(logs) == 1
    assert logs[0].status == CommentStatus.POSTED.value
    assert logs[0].is_economy_stub is True
    assert logs[0].comment_text == "сгенерированный коммент"


async def test_post_comment_postbot_forward_logs_postbot_marker(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    source = SimpleNamespace(id=1, text="готовый пост", message="готовый пост", media=None)
    _set(
        session, campaign_id,
        postbot_forward_enabled=True, postbot_message_ids=[1], discussion_group_id=555,
    )
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)

    client = _PostbotClient(source=source)
    ctx = _ctx(session, client)

    posted = await runner.post_comment(
        ctx, campaign_id, account_id, "", 100, 100,
        postbot_forward=True,
    )
    assert posted is not None
    logs = CommentLogRepository(session).list_by_campaign(campaign_id)
    assert len(logs) == 1
    assert logs[0].comment_text == "[Postbot #1]"
    assert logs[0].status == CommentStatus.POSTED.value


async def test_post_comment_empty_text_safety_net_regenerates(session, monkeypatch):
    """economy_stub=True был запланирован, но кампания успела выключить
    token_economy_enabled до отправки — text пуст, ожидаем regenerate, а не
    пустое сообщение."""
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, token_economy_enabled=False, discussion_group_id=555)
    account_id = _make_account(session, status="assigned", campaign_id=campaign_id)

    client = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=7)))
    ctx = _ctx(session, client)
    ctx["llm_provider"] = _CaptchaLLM("safety-net текст")

    posted = await runner.post_comment(
        ctx, campaign_id, account_id, "", 100, 100,
        economy_stub=True, post_text="пост",
    )
    assert posted == 7
    client.send_message.assert_awaited_once()
    assert client.send_message.await_args.args[1] == "safety-net текст"
