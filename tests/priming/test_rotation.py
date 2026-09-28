"""Тесты для :func:`modules.priming.worker.rotation.pick_trigger_action`
(prompt 5.2).
"""

from __future__ import annotations

import random

import pytest

from modules.priming.schemas.enums import (
    TriggerAction,
    TriggerRotationStrategy,
)
from modules.priming.worker.rotation import pick_trigger_action


ACTIONS = [
    TriggerAction.SECRET_CHAT_REQUEST.value,
    TriggerAction.SET_TTL_1D.value,
    TriggerAction.CONTACT_ADDED.value,
]


def test_pick_empty_raises() -> None:
    with pytest.raises(ValueError):
        pick_trigger_action([], TriggerRotationStrategy.RANDOM)


def test_round_robin_cycles_deterministically() -> None:
    picks = [
        pick_trigger_action(ACTIONS, TriggerRotationStrategy.ROUND_ROBIN, counter=i)
        for i in range(len(ACTIONS) * 3)
    ]
    assert [p.value for p in picks[: len(ACTIONS)]] == ACTIONS
    # цикл повторяется
    assert [p.value for p in picks[len(ACTIONS) : 2 * len(ACTIONS)]] == ACTIONS
    assert [p.value for p in picks[2 * len(ACTIONS) :]] == ACTIONS


def test_random_is_approximately_uniform_over_1000_rolls() -> None:
    rng = random.Random(1234)
    counts: dict[str, int] = {a: 0 for a in ACTIONS}
    for _ in range(1000):
        p = pick_trigger_action(
            ACTIONS, TriggerRotationStrategy.RANDOM, rng=rng
        )
        counts[p.value] += 1
    expected = 1000 / len(ACTIONS)
    for a in ACTIONS:
        # ±30% от ожидаемого — с запасом
        assert abs(counts[a] - expected) < expected * 0.3, counts


def test_weighted_falls_back_to_uniform_in_mvp() -> None:
    rng = random.Random(42)
    counts: dict[str, int] = {a: 0 for a in ACTIONS}
    for _ in range(1000):
        p = pick_trigger_action(
            ACTIONS, TriggerRotationStrategy.WEIGHTED, rng=rng
        )
        counts[p.value] += 1
    expected = 1000 / len(ACTIONS)
    for a in ACTIONS:
        assert abs(counts[a] - expected) < expected * 0.3, counts


def test_single_action_always_returned() -> None:
    only = [TriggerAction.SET_TTL_OFF.value]
    for strategy in TriggerRotationStrategy:
        for i in range(10):
            p = pick_trigger_action(only, strategy, counter=i)
            assert p is TriggerAction.SET_TTL_OFF
