"""Тесты линейной рампы warmup-профилей (prompt 6.1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.config.priming_warmup import (
    RAMP_LAST_DAY,
    WARMUP_PROFILES,
    effective_daily_limit,
    effective_delay_range,
    warmup_day,
)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


def test_warmup_day_none_is_day1(now: datetime) -> None:
    assert warmup_day(None, now) == 1


def test_warmup_day_counts_from_started(now: datetime) -> None:
    assert warmup_day(now, now) == 1
    assert warmup_day(now - timedelta(days=1), now) == 2
    assert warmup_day(now - timedelta(days=6), now) == 7
    assert warmup_day(now - timedelta(days=30), now) == 31


def test_warmup_day_ignores_naive_tz(now: datetime) -> None:
    started = (now - timedelta(days=3)).replace(tzinfo=None)
    assert warmup_day(started, now) == 4


def test_effective_daily_limit_day1_matches_profile(now: datetime) -> None:
    for name, cfg in WARMUP_PROFILES.items():
        limit = effective_daily_limit(name, now, now)
        assert limit == cfg.day1_limit, name


def test_effective_daily_limit_day7_plus_matches_profile(now: datetime) -> None:
    for name, cfg in WARMUP_PROFILES.items():
        started = now - timedelta(days=RAMP_LAST_DAY - 1)
        assert effective_daily_limit(name, started, now) == cfg.day7_limit
        # плато после day7
        started_plateau = now - timedelta(days=30)
        assert (
            effective_daily_limit(name, started_plateau, now) == cfg.day7_limit
        )


def test_effective_daily_limit_interpolates_linearly(now: datetime) -> None:
    # warm: 15 → 30 за 6 дней → шаг 2.5, day4 ≈ 15 + 3*2.5 = 22 или 23
    started = now - timedelta(days=3)  # day4
    limit = effective_daily_limit("warm", started, now)
    assert limit in (22, 23)


def test_effective_daily_limit_respects_campaign_cap(now: datetime) -> None:
    # hot day7 = 40; кап кампании 10 — рампа не должна перерасти кап
    started = now - timedelta(days=10)
    assert effective_daily_limit("hot", started, now, campaign_cap=10) == 10
    # но не меньше 1
    assert (
        effective_daily_limit("hot", None, now, campaign_cap=0) == 1
    )


def test_effective_daily_limit_unknown_profile_falls_back(now: datetime) -> None:
    assert effective_daily_limit("mystery", None, now, campaign_cap=17) == 17
    assert effective_daily_limit("mystery", None, now) == 1


def test_effective_delay_range_returns_profile_pair() -> None:
    for name, cfg in WARMUP_PROFILES.items():
        assert effective_delay_range(name) == (cfg.delay_min, cfg.delay_max)


def test_effective_delay_range_unknown_defaults() -> None:
    assert effective_delay_range("mystery") == (60, 180)
