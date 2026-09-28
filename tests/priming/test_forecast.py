"""Расчёт прогноза (prompt 7.4) с фиксированными входами."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from modules.priming.api.forecast import (
    ForecastAccountView,
    ForecastCampaignView,
    compute_forecast,
)
from modules.priming.schemas.enums import ExecutionOutcome, PrimingAccountState


NOW = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)


def _campaign(**over) -> ForecastCampaignView:
    base = {"warmup_profile": "warm", "daily_limit_per_account": 30}
    base.update(over)
    return ForecastCampaignView(**base)


def _account(**over) -> ForecastAccountView:
    base = {
        "state": PrimingAccountState.IDLE.value,
        "primes_today": 0,
        "warmup_started_at": NOW - timedelta(days=10),  # плато
        "next_available_at": None,
    }
    base.update(over)
    return ForecastAccountView(**base)


def test_empty_history_zero_flood() -> None:
    result = compute_forecast(_campaign(), [_account()], recent_outcomes=[], now=NOW)
    assert result.expected_flood_per_hour == 0
    assert result.sample_size == 0
    # remaining = 30, /24ч ≈ 1
    assert result.expected_primes_per_hour == 1


def test_flood_rate_multiplies_expected() -> None:
    # 100 outcome, 30% flood → 30% от per-hour
    outcomes = [ExecutionOutcome.FLOOD_WAIT.value] * 30 + [
        ExecutionOutcome.PRIMED.value
    ] * 70
    accounts = [_account(primes_today=0) for _ in range(10)]  # 10*30=300 остатка
    result = compute_forecast(_campaign(), accounts, outcomes, now=NOW)
    # per_hour ≈ 300/24 = 12-13
    assert 12 <= result.expected_primes_per_hour <= 13
    assert result.expected_flood_per_hour == round(
        result.expected_primes_per_hour * 0.3,
    )


def test_quarantined_accounts_dont_contribute() -> None:
    accounts = [
        _account(state=PrimingAccountState.QUARANTINED.value),
        _account(state=PrimingAccountState.QUARANTINED.value),
        _account(primes_today=0),  # только один вносит 30 остатка
    ]
    result = compute_forecast(_campaign(), accounts, [], now=NOW)
    assert result.expected_primes_per_hour == round(30 / 24)


def test_primes_today_subtracted_from_daily() -> None:
    # день1: warm = 15; 12 сделано → остаток 3.
    accounts = [
        _account(
            primes_today=12,
            warmup_started_at=NOW,  # day1
        ),
    ]
    result = compute_forecast(_campaign(), accounts, [], now=NOW)
    # 3 / 24 = 0 при round
    assert result.expected_primes_per_hour == 0


def test_best_start_after_uses_min_next_available() -> None:
    accounts = [
        _account(
            state=PrimingAccountState.COOLDOWN.value,
            next_available_at=NOW + timedelta(minutes=10),
        ),
        _account(
            state=PrimingAccountState.COOLDOWN.value,
            next_available_at=NOW + timedelta(minutes=3),
        ),
    ]
    result = compute_forecast(_campaign(), accounts, [], now=NOW)
    assert result.best_start_after == 180


def test_best_start_zero_when_any_ready() -> None:
    accounts = [
        _account(
            state=PrimingAccountState.COOLDOWN.value,
            next_available_at=NOW + timedelta(minutes=10),
        ),
        _account(state=PrimingAccountState.IDLE.value),
    ]
    result = compute_forecast(_campaign(), accounts, [], now=NOW)
    assert result.best_start_after == 0


def test_zero_remaining_returns_zero_wait() -> None:
    accounts = [_account(primes_today=30)]  # весь лимит выбран
    result = compute_forecast(_campaign(), accounts, [], now=NOW)
    assert result.expected_primes_per_hour == 0
    assert result.best_start_after == 0
