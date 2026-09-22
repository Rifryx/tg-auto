"""Тесты persona-based targets и error-категоризации (этап 10)."""

from __future__ import annotations

import random
from unittest.mock import AsyncMock

import pytest

from core.enums import WarmingActionType, WarmingActivityStatus
from worker.warming.actions.base import (
    DISCOVERY_CHANNELS,
    _categorize_error,
    pick_target,
)


class _FakePersona:
    """Мимикрирует Persona для helper'а — держит только поле interests."""

    def __init__(self, interests):
        self.interests = interests


# ── pick_target ─────────────────────────────────────────────────────────────


def test_pick_target_uses_persona_interests():
    persona = _FakePersona(interests=["@channel_a", "@channel_b"])
    rng = random.Random(1)
    got = pick_target(rng, persona, "channel", DISCOVERY_CHANNELS)
    assert got in {"@channel_a", "@channel_b"}


def test_pick_target_falls_back_when_persona_none():
    got = pick_target(random.Random(2), None, "channel", DISCOVERY_CHANNELS)
    assert got in DISCOVERY_CHANNELS


def test_pick_target_falls_back_when_interests_empty():
    persona = _FakePersona(interests=[])
    got = pick_target(random.Random(3), persona, "channel", DISCOVERY_CHANNELS)
    assert got in DISCOVERY_CHANNELS


def test_pick_target_deterministic_by_rng():
    persona = _FakePersona(interests=["a", "b", "c", "d"])
    got1 = pick_target(random.Random(42), persona, "channel", DISCOVERY_CHANNELS)
    got2 = pick_target(random.Random(42), persona, "channel", DISCOVERY_CHANNELS)
    assert got1 == got2


# ── error categorization ───────────────────────────────────────────────────


def test_categorize_unknown_error():
    class RandomBoom(Exception):
        pass
    assert _categorize_error(RandomBoom()) == "unknown"


def test_categorize_rate_limit_by_name():
    class FloodWaitError(Exception):
        pass
    assert _categorize_error(FloodWaitError()) == "rate_limit"


def test_categorize_ephemeral_target():
    class ChatWriteForbiddenError(Exception):
        pass
    class ChannelPrivateError(Exception):
        pass
    assert _categorize_error(ChatWriteForbiddenError()) == "target_broken"
    assert _categorize_error(ChannelPrivateError()) == "target_broken"


def test_categorize_fatal():
    class SessionRevokedError(Exception):
        pass
    class PhoneNumberBannedError(Exception):
        pass
    assert _categorize_error(SessionRevokedError()) == "fatal"
    assert _categorize_error(PhoneNumberBannedError()) == "fatal"


# ── decorated action puts category into meta ───────────────────────────────


@pytest.mark.asyncio
async def test_decorated_action_records_error_category_in_meta():
    """При провале action записывает error_category в meta."""
    from worker.warming.actions.subscribe_channel import execute

    class ChatWriteForbiddenError(Exception):
        pass

    class _FakeAccount:
        id = 1

    class _Client:
        async def __call__(self, *_args, **_kwargs):
            raise ChatWriteForbiddenError("closed channel")

    # session_factory=None → без health-обёртки; вокруг ошибка проходит в наш
    # try/except (в base.py::action.decorator).
    result = await execute(_Client(), _FakeAccount(), persona=_FakePersona(["x"]))
    assert result.status is WarmingActivityStatus.FAILED
    assert result.action_type is WarmingActionType.SUBSCRIBE_CHANNEL
    assert result.meta is not None
    assert result.meta["error_category"] == "target_broken"


@pytest.mark.asyncio
async def test_decorated_action_uses_persona_target():
    """subscribe_channel c persona.interests берёт из interests."""
    from worker.warming.actions.subscribe_channel import execute

    class _FakeAccount:
        id = 1

    called_with = {}

    class _Client:
        async def __call__(self, request):
            called_with["request"] = request
            return None

    persona = _FakePersona(interests=["@my_channel"])
    result = await execute(
        _Client(), _FakeAccount(), persona=persona, rng=random.Random(0)
    )
    assert result.status is WarmingActivityStatus.DONE
    assert result.target == "@my_channel"
