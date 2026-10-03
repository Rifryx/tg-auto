"""Пресеты прогрева кампаний прайминга (spec §11.1, prompt 6.1).

Профиль задаёт, сколько прайминг-акций аккаунт может делать в день
и в каком диапазоне задержек между целями — начиная с первого дня
кампании (day 1) и вплоть до day 7. Между этими точками — линейная
интерполяция, дальше — плато.

Executor и orchestrator дёргают :func:`effective_daily_limit` /
:func:`effective_delay_range`, чтобы получить эффективный лимит для
конкретного аккаунта с учётом того, сколько дней он уже работает
в кампании (``warmup_started_at`` живёт на ``PrimingCampaignAccount``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class WarmupProfileConfig:
    """Пара точек (day1 / day7) — между ними линейная рампа."""

    day1_limit: int
    day7_limit: int
    delay_min: int
    delay_max: int


WARMUP_PROFILES: dict[str, WarmupProfileConfig] = {
    "cold": WarmupProfileConfig(
        day1_limit=5, day7_limit=20, delay_min=200, delay_max=600
    ),
    "warm": WarmupProfileConfig(
        day1_limit=15, day7_limit=30, delay_min=60, delay_max=200
    ),
    "hot": WarmupProfileConfig(
        day1_limit=35, day7_limit=40, delay_min=20, delay_max=60
    ),
}

# День, к которому лимит достигает day7_limit. До и после — плато /
# линейная интерполяция.
RAMP_LAST_DAY = 7


def warmup_day(
    started_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> int:
    """Возвращает номер дня прогрева (1..∞).

    ``started_at`` = None означает, что аккаунт ещё ни разу не грелся —
    считаем day1. Дни считаем по UTC-суткам, включительно с first-day.
    """
    if started_at is None:
        return 1
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    delta_days = (ref.date() - started_at.date()).days
    return max(1, delta_days + 1)


def _lerp(a: int, b: int, day: int) -> int:
    if day <= 1:
        return a
    if day >= RAMP_LAST_DAY:
        return b
    span = RAMP_LAST_DAY - 1
    return int(round(a + (b - a) * (day - 1) / span))


def effective_daily_limit(
    profile: str,
    started_at: Optional[datetime],
    now: Optional[datetime] = None,
    *,
    campaign_cap: Optional[int] = None,
) -> int:
    """Дневной лимит с учётом рампы. Ограничивается ``campaign_cap``,
    если тот задан (кампания может урезать даже прогретый профиль).
    """
    cfg = WARMUP_PROFILES.get(profile)
    if cfg is None:
        # неизвестный профиль — падаем в кампанийский cap либо в 1
        return campaign_cap if campaign_cap is not None else 1
    day = warmup_day(started_at, now)
    limit = _lerp(cfg.day1_limit, cfg.day7_limit, day)
    if campaign_cap is not None:
        limit = min(limit, campaign_cap)
    return max(1, limit)


def effective_delay_range(profile: str) -> tuple[int, int]:
    """Пара (min, max) секунд между целями для профиля. Диапазон
    сейчас не рампится — рампим только лимит; диапазон задаёт стиль.
    """
    cfg = WARMUP_PROFILES.get(profile)
    if cfg is None:
        return (60, 180)
    return (cfg.delay_min, cfg.delay_max)


__all__ = [
    "WarmupProfileConfig",
    "WARMUP_PROFILES",
    "RAMP_LAST_DAY",
    "warmup_day",
    "effective_daily_limit",
    "effective_delay_range",
]
