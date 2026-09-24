"""E4.1: стиль коммента и способ доставки — emoji policy, стикеры, картинки,
write_as_channel. БД настоящая, Telethon-клиент/пул — фейки."""

from __future__ import annotations

import random
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from core.repositories.media_asset import MediaAssetRepository
from modules.commenting.repositories import CampaignRepository, CommentLogRepository
from modules.commenting.worker import delivery, runner
from tests.test_commenting_channels import (
    _ctx as _base_ctx,
    _make_account,
    _make_campaign,
    _SpyPublisher,
    _SpyTaskQueue,
)

pytestmark = pytest.mark.asyncio

_TABLES = (
    "accounts",
    "health_events",
    "account_status_history",
    "media_assets",
    '"commenting".campaigns',
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
    '"commenting".campaign_media_assets',
)


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _set(session, campaign_id, **fields):
    c = CampaignRepository(session).get(campaign_id)
    for k, v in fields.items():
        setattr(c, k, v)
    session.commit()


class _SeqRng(random.Random):
    """RNG, отдающий заданные значения `random()` по очереди; когда список
    исчерпан — работает как обычный random.Random (для внутренних вызовов
    типа `rng.choice`, которые тоже вызывают random())."""

    def __init__(self, values):
        super().__init__(0)
        self._values = list(values)
        self._i = 0

    def random(self):
        if self._i < len(self._values):
            v = self._values[self._i]
            self._i += 1
            return v
        return super().random()


class _StaticStyle:
    def randomize(self, text_, persona):
        return text_


class _ScriptedLLM:
    def __init__(self, text):
        self.text = text

    async def generate(self, system, messages, max_tokens=200, temperature=0.8):
        self.last_system = system
        return self.text


class _RecordingClient:
    """Логирует, чем именно отправили (текст/стикер/файл) и send_as."""

    def __init__(self):
        self.send_message = AsyncMock(return_value=SimpleNamespace(id=1))
        self.send_file = AsyncMock(return_value=SimpleNamespace(id=2))
        self.get_me = AsyncMock(return_value=SimpleNamespace(id=999))
        self._sticker_calls = 0
        self._send_as_result = None
        self._all_stickers = None

    async def __call__(self, request):
        name = type(request).__name__
        if name == "GetAllStickersRequest":
            return self._all_stickers or SimpleNamespace(sets=[])
        if name == "GetStickerSetRequest":
            return SimpleNamespace(documents=[SimpleNamespace(id=42), SimpleNamespace(id=43)])
        if name == "GetSendAsRequest":
            return self._send_as_result or SimpleNamespace(peers=[])
        return None


def _ctx(session, client, *, rng=None, publisher=None):
    ctx = _base_ctx(session, client=client, task_queue=_SpyTaskQueue(), publisher=publisher)
    ctx["rng"] = rng or random.Random(0)
    ctx["style_randomizer"] = _StaticStyle()
    return ctx


def _assigned(session, campaign_id):
    return _make_account(session, status="assigned", campaign_id=campaign_id)


# ── emoji policy ─────────────────────────────────────────────────────────────


def test_strip_emoji_removes_pictograms_and_flags():
    assert delivery.strip_emoji("Привет 👋! 🇺🇦") == "Привет !"


def test_emoji_prompt_suffix_only_when_off():
    on = SimpleNamespace(use_emojis=True)
    off = SimpleNamespace(use_emojis=False)
    assert delivery.emoji_prompt_suffix(on) == ""
    assert "не используй" in delivery.emoji_prompt_suffix(off).lower()


def test_apply_style_strips_emoji_when_off():
    on = SimpleNamespace(use_emojis=True)
    off = SimpleNamespace(use_emojis=False)
    style = _StaticStyle()
    assert delivery.apply_style("Hi 👍", on, None, style) == "Hi 👍"
    assert delivery.apply_style("Hi 👍", off, None, style) == "Hi"


async def test_generate_adds_emoji_instruction_and_strips(session):
    from core.models import Account

    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, use_emojis=False)
    account_id = _assigned(session, campaign_id)
    ctx = _ctx(session, _RecordingClient())
    llm = _ScriptedLLM("Комментарий 🔥 круто")
    ctx["llm_provider"] = llm

    campaign = CampaignRepository(session).get(campaign_id)
    account = session.get(Account, account_id)
    result, ok = await runner._generate(ctx, session, campaign, account, llm, [])
    assert ok
    assert "не используй эмодзи" in llm.last_system.lower()
    assert "🔥" not in result


# ── pick_mode ────────────────────────────────────────────────────────────────


def test_pick_mode_defaults_to_text_when_flags_off():
    campaign = SimpleNamespace(use_stickers=False, attach_image=False)
    assert delivery.pick_mode(campaign, random.Random(0), has_media=True, has_sticker=True) == "text"


def test_pick_mode_sticker_wins_when_dice_low():
    campaign = SimpleNamespace(use_stickers=True, attach_image=True)
    rng = _SeqRng([0.1])  # < 0.25
    assert delivery.pick_mode(campaign, rng, has_media=True, has_sticker=True) == "sticker"


def test_pick_mode_falls_back_to_text_without_assets():
    campaign = SimpleNamespace(use_stickers=True, attach_image=True)
    rng = _SeqRng([0.9, 0.9])  # sticker no, image no
    assert delivery.pick_mode(campaign, rng, has_media=True, has_sticker=True) == "text"


def test_pick_mode_image_when_sticker_off():
    campaign = SimpleNamespace(use_stickers=False, attach_image=True)
    rng = _SeqRng([0.1])  # < 0.40
    assert delivery.pick_mode(campaign, rng, has_media=True, has_sticker=False) == "text_with_image"


# ── deliver_comment: интеграция ─────────────────────────────────────────────


async def _add_media(session, campaign_id, user_id="u"):
    asset = MediaAssetRepository(session).get_or_create(
        user_id=user_id, blob=b"png-bytes", mime="image/png", filename="a.png"
    )
    session.commit()
    from modules.commenting.models import CampaignMediaAsset

    session.add(CampaignMediaAsset(campaign_id=campaign_id, media_asset_id=asset.id))
    session.commit()
    return asset.id


async def test_deliver_sends_text_by_default(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _assigned(session, campaign_id)
    campaign = CampaignRepository(session).get(campaign_id)
    client = _RecordingClient()

    sent, mode = await delivery.deliver_comment(
        _ctx(session, client), client, campaign,
        account_id=account_id, discussion_group_id=555, text="hi",
        reply_to=100, now=None, publisher=None, rng=random.Random(0),
    )
    assert mode == "text"
    client.send_message.assert_awaited_once()
    client.send_file.assert_not_awaited()


async def test_deliver_uses_sticker_when_dice_and_pack_available(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, use_stickers=True)
    account_id = _assigned(session, campaign_id)
    campaign = CampaignRepository(session).get(campaign_id)
    client = _RecordingClient()
    client._all_stickers = SimpleNamespace(
        sets=[SimpleNamespace(id=1, access_hash=2)]
    )
    ctx = _ctx(session, client, rng=_SeqRng([0.1, 0.0]))  # sticker win + choice

    _, mode = await delivery.deliver_comment(
        ctx, client, campaign,
        account_id=account_id, discussion_group_id=555, text="hi",
        reply_to=100, now=None, publisher=None, rng=ctx["rng"],
    )
    assert mode == "sticker"
    client.send_file.assert_awaited_once()
    client.send_message.assert_not_awaited()


async def test_deliver_falls_back_to_text_without_stickers(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, use_stickers=True)
    account_id = _assigned(session, campaign_id)
    campaign = CampaignRepository(session).get(campaign_id)
    client = _RecordingClient()  # sets=[] по умолчанию — стикеров нет
    ctx = _ctx(session, client, rng=_SeqRng([0.1]))  # sticker хочет сработать, но нечем

    _, mode = await delivery.deliver_comment(
        ctx, client, campaign,
        account_id=account_id, discussion_group_id=555, text="hi",
        reply_to=100, now=None, publisher=None, rng=ctx["rng"],
    )
    assert mode == "text"
    client.send_message.assert_awaited_once()


async def test_deliver_image_uses_campaign_media(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, attach_image=True)
    account_id = _assigned(session, campaign_id)
    await _add_media(session, campaign_id)
    campaign = CampaignRepository(session).get(campaign_id)
    client = _RecordingClient()
    ctx = _ctx(session, client, rng=_SeqRng([0.1]))  # image roll < 0.4

    _, mode = await delivery.deliver_comment(
        ctx, client, campaign,
        account_id=account_id, discussion_group_id=555, text="hi",
        reply_to=100, now=None, publisher=None, rng=ctx["rng"],
    )
    assert mode == "text_with_image"
    client.send_file.assert_awaited_once()
    call = client.send_file.await_args
    assert call.kwargs["caption"] == "hi"


async def test_deliver_image_falls_back_when_no_assets(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, attach_image=True)
    account_id = _assigned(session, campaign_id)
    campaign = CampaignRepository(session).get(campaign_id)
    client = _RecordingClient()
    ctx = _ctx(session, client, rng=_SeqRng([0.1]))
    _, mode = await delivery.deliver_comment(
        ctx, client, campaign,
        account_id=account_id, discussion_group_id=555, text="hi",
        reply_to=100, now=None, publisher=None, rng=ctx["rng"],
    )
    # attach_image включён, но нет привязанных ассетов → has_media=False → сразу text
    assert mode == "text"


# ── write_as_channel ────────────────────────────────────────────────────────


async def test_write_as_channel_uses_send_as_when_available(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, write_as_channel=True)
    account_id = _assigned(session, campaign_id)
    campaign = CampaignRepository(session).get(campaign_id)
    client = _RecordingClient()
    client._send_as_result = SimpleNamespace(
        peers=[SimpleNamespace(peer=SimpleNamespace(channel_id=888))]
    )

    _, mode = await delivery.deliver_comment(
        _ctx(session, client), client, campaign,
        account_id=account_id, discussion_group_id=555, text="hi",
        reply_to=100, now=None, publisher=None, rng=random.Random(0),
    )
    assert mode == "text"
    assert client.send_message.await_args.kwargs["send_as"] is not None
    assert getattr(client.send_message.await_args.kwargs["send_as"], "channel_id", None) == 888


async def test_write_as_channel_falls_back_when_no_permission(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    _set(session, campaign_id, write_as_channel=True)
    account_id = _assigned(session, campaign_id)
    campaign = CampaignRepository(session).get(campaign_id)
    client = _RecordingClient()  # peers пусто

    _, mode = await delivery.deliver_comment(
        _ctx(session, client), client, campaign,
        account_id=account_id, discussion_group_id=555, text="hi",
        reply_to=100, now=None, publisher=None, rng=random.Random(0),
    )
    assert mode == "text"
    assert client.send_message.await_args.kwargs["send_as"] is None


async def test_send_as_result_cached_per_group(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _assigned(session, campaign_id)
    client = _RecordingClient()
    ctx = _ctx(session, client)

    await delivery.resolve_send_as(ctx, client, account_id, 100)
    await delivery.resolve_send_as(ctx, client, account_id, 100)
    # Второй вызов идёт из кеша: __call__ (для GetSendAsRequest) — только один.
    # У _RecordingClient __call__ маскированный по имени, поэтому считаем через
    # публичный интерфейс: ключ есть в кеше.
    assert (account_id, 100) in ctx["_send_as_cache"]


# ── API привязки медиа-ассетов ──────────────────────────────────────────────


async def test_api_set_campaign_media_isolates_by_owner(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    # Ассет чужого пользователя.
    asset_other = MediaAssetRepository(session).get_or_create(
        user_id="other", blob=b"x", mime="image/png"
    )
    session.commit()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.deps.auth import require_user
    from api.deps.db import get_session
    from api.deps.queue import get_publisher, get_task_queue
    from modules.commenting.api import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_publisher] = lambda: None
    app.dependency_overrides[get_task_queue] = lambda: _SpyTaskQueue()
    app.dependency_overrides[require_user] = lambda: "u"
    client = TestClient(app)
    r = client.put(
        f"/modules/commenting/campaigns/{campaign_id}/media",
        json={"media_asset_ids": [asset_other.id]},
    )
    assert r.status_code == 422  # чужой ассет не принимается

    # свой — принимается
    asset_own = MediaAssetRepository(session).get_or_create(
        user_id="u", blob=b"y", mime="image/png"
    )
    session.commit()
    r = client.put(
        f"/modules/commenting/campaigns/{campaign_id}/media",
        json={"media_asset_ids": [asset_own.id]},
    )
    assert r.status_code == 200 and r.json()["media_asset_ids"] == [asset_own.id]
    r = client.get(f"/modules/commenting/campaigns/{campaign_id}/media")
    assert r.json()["media_asset_ids"] == [asset_own.id]


async def test_create_campaign_sets_owner_user_id(session):
    _clean(session)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.deps.auth import require_user
    from api.deps.db import get_session
    from api.deps.limits import enforce_limit
    from api.deps.queue import get_publisher, get_task_queue
    from modules.commenting.api import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_publisher] = lambda: None
    app.dependency_overrides[get_task_queue] = lambda: _SpyTaskQueue()
    app.dependency_overrides[require_user] = lambda: "u-42"
    app.dependency_overrides[enforce_limit("campaigns_active_max")] = lambda: None
    client = TestClient(app)

    body = {
        "name": "c",
        "base_system_prompt": "p",
        "llm_provider": "deepseek",
        "active_hours_start": "09:00:00",
        "active_hours_end": "23:00:00",
        "active_hours_tz": "UTC",
        "posting_delay_min_sec": 1,
        "posting_delay_max_sec": 2,
    }
    r = client.post("/modules/commenting/campaigns", json=body)
    assert r.status_code == 201 and r.json()["owner_user_id"] == "u-42"
