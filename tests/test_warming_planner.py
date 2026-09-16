"""Юнит-тесты Planner v2 (этап 10 УТП). Без БД, без сети.

Проверяют:
* personal-окно активности из персоны переопределяет config;
* веса действий сдвигаются под personality_tags;
* Health Score < 40 гасит агрессивные действия и удлиняет интервал x2.
"""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

from core.enums import WarmingActionType, WarmingProfile
from worker.warming.planner import (
    _compute_weights,
    choose_action,
    due_interval,
    is_within_active_window,
    next_interval,
)


def _persona(**kwargs):
    base = SimpleNamespace(
        personality_tags=[],
        timezone=None,
        active_hours_start=None,
        active_hours_end=None,
        interests=[],
    )
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


# ── activity window ──────────────────────────────────────────────────────────


def test_active_window_uses_persona_tz_when_set():
    # 00:00 UTC = 12:00 в Asia/Tokyo → внутри окна 09–23 персоны.
    persona = _persona(
        timezone="Asia/Tokyo",
        active_hours_start=time(9, 0),
        active_hours_end=time(23, 0),
    )
    now = datetime(2026, 9, 16, 0, 0, tzinfo=timezone.utc)
    assert is_within_active_window(now, persona=persona) is True


def test_active_window_persona_night_owl():
    # Персона активна 22:00–06:00 (окно через полночь).
    persona = _persona(
        timezone="UTC",
        active_hours_start=time(22, 0),
        active_hours_end=time(6, 0),
    )
    assert is_within_active_window(
        datetime(2026, 9, 16, 3, 0, tzinfo=timezone.utc), persona=persona
    ) is True
    assert is_within_active_window(
        datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc), persona=persona
    ) is False


# ── action weights по тегам персоны ──────────────────────────────────────────


def test_weights_default_uniform_without_persona():
    weights = _compute_weights(None, health_score=None)
    assert weights == [1.0] * len(list(WarmingActionType))


def test_weights_formal_dampens_reactions_and_joins():
    persona = _persona(personality_tags=["formal"])
    weights = _compute_weights(persona, health_score=None)
    types = list(WarmingActionType)
    w = dict(zip(types, weights))
    assert w[WarmingActionType.REACTION] < 1.0
    assert w[WarmingActionType.JOIN_GROUP] < 1.0
    assert w[WarmingActionType.IDLE_ONLINE] > 1.0


def test_weights_lurker_prefers_reading():
    persona = _persona(personality_tags=["lurker"])
    weights = dict(zip(list(WarmingActionType), _compute_weights(persona, None)))
    assert weights[WarmingActionType.READ_HISTORY] > weights[WarmingActionType.SUBSCRIBE_CHANNEL]
    assert weights[WarmingActionType.VIEW_MEDIA] > weights[WarmingActionType.REACTION]


# ── health-адаптация ─────────────────────────────────────────────────────────


def test_low_health_score_dampens_aggressive_actions():
    persona = _persona(personality_tags=[])
    healthy = dict(zip(list(WarmingActionType), _compute_weights(persona, health_score=90)))
    at_risk = dict(zip(list(WarmingActionType), _compute_weights(persona, health_score=20)))
    assert at_risk[WarmingActionType.SUBSCRIBE_CHANNEL] < healthy[WarmingActionType.SUBSCRIBE_CHANNEL]
    assert at_risk[WarmingActionType.JOIN_GROUP] < healthy[WarmingActionType.JOIN_GROUP]
    assert at_risk[WarmingActionType.IDLE_ONLINE] > healthy[WarmingActionType.IDLE_ONLINE]


def test_next_interval_doubles_for_at_risk():
    rng = random.Random(42)
    base = next_interval(WarmingProfile.MEDIUM.value, rng, health_score=80)
    rng = random.Random(42)  # тот же seed для честного сравнения
    slowed = next_interval(WarmingProfile.MEDIUM.value, rng, health_score=20)
    # с fix seed'ом остальные факторы совпадают → отношение ≈ 2.0.
    assert 1.9 <= slowed.total_seconds() / base.total_seconds() <= 2.1


def test_due_interval_doubles_for_at_risk():
    base = due_interval(WarmingProfile.MEDIUM.value, health_score=80)
    slowed = due_interval(WarmingProfile.MEDIUM.value, health_score=20)
    assert slowed == base * 2


def test_choose_action_seeded_deterministic():
    rng = random.Random(7)
    persona = _persona(personality_tags=["lurker"])
    picks = [choose_action(rng, persona, health_score=90) for _ in range(20)]
    # У lurker'а REACTION и JOIN_GROUP редки — их доля <30% от общего числа.
    aggressive = sum(
        1 for p in picks
        if p in (WarmingActionType.JOIN_GROUP, WarmingActionType.REACTION)
    )
    assert aggressive < len(picks) * 0.3
