"""Прогноз «Что произойдёт за час» для кампании (prompt 7.4, spec §9.2).

Считает три числа для карточки-симуляции на финальном шаге мастера:

* ``expected_primes_per_hour`` — сколько праймов кампания в среднем
  сделает за следующий час при текущей конфигурации;
* ``expected_flood_per_hour`` — сколько из них по нашим оценкам
  свалится в flood_wait (для warning-полосы);
* ``best_start_after`` — сколько секунд подождать, чтобы попасть
  «в окно» (если сейчас все аккаунты в cooldown, покажем ETA).

Формула сознательно простая: MVP для UI, точность растёт по мере
накопления execution_log; сюда не тянем ML — пока хватает средних.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

from core.config.priming_warmup import effective_daily_limit
from modules.priming.schemas.enums import (
    ExecutionOutcome,
    PrimingAccountState,
)


HOURS_PER_DAY = 24
# Средняя доля активных часов в сутках при равномерном распределении.
ACTIVE_HOURS_RATIO = HOURS_PER_DAY / 24  # 1.0 — сейчас нет ночных пауз


@dataclass
class ForecastAccountView:
    """Минимальный срез аккаунта — то, что нужно для прогноза."""

    state: str
    primes_today: int
    warmup_started_at: Optional[datetime]
    next_available_at: Optional[datetime]


@dataclass
class ForecastCampaignView:
    warmup_profile: str
    daily_limit_per_account: int


@dataclass
class ForecastResult:
    expected_primes_per_hour: int
    expected_flood_per_hour: int
    best_start_after: int  # секунды; 0 — можно стартовать сейчас
    sample_size: int       # сколько execution_log записей использовалось


def compute_forecast(
    campaign: ForecastCampaignView,
    accounts: Iterable[ForecastAccountView],
    recent_outcomes: list[str],
    *,
    now: Optional[datetime] = None,
) -> ForecastResult:
    """Считает прогноз.

    * expected_primes_per_hour = сумма (эффективный дневной лимит −
      уже сделано сегодня) по всем не-quarantined аккаунтам, поделённая
      на оставшиеся активные часы (для UI хватает грубого равномерного
      распределения по 24ч);
    * expected_flood_per_hour = expected_primes * flood_rate из окна
      recent_outcomes (или 0 при пустой истории);
    * best_start_after = минимальный next_available_at − now из тех,
      у кого он в будущем; 0, если хоть один аккаунт готов.
    """
    now = now or datetime.now(timezone.utc)

    remaining_daily = 0
    best_wait: Optional[int] = None
    any_ready = False

    for a in accounts:
        if a.state == PrimingAccountState.QUARANTINED.value:
            continue
        eff_limit = effective_daily_limit(
            campaign.warmup_profile,
            a.warmup_started_at,
            now,
            campaign_cap=campaign.daily_limit_per_account,
        )
        remaining_today = max(0, eff_limit - a.primes_today)
        remaining_daily += remaining_today

        wait: Optional[int] = None
        if a.next_available_at is not None:
            delta = int((a.next_available_at - now).total_seconds())
            if delta > 0:
                wait = delta
        if wait is None and a.state in (
            PrimingAccountState.IDLE.value,
            PrimingAccountState.WORKING.value,
        ):
            any_ready = True
        elif wait is not None:
            best_wait = wait if best_wait is None else min(best_wait, wait)

    # Грубая равномерность: делим оставшийся дневной лимит на 24ч.
    # Верхняя оценка часовой нагрузки — вся остаточная квота.
    per_hour = int(round(remaining_daily / max(1, HOURS_PER_DAY * ACTIVE_HOURS_RATIO)))
    per_hour = min(per_hour, remaining_daily)

    flood_rate = 0.0
    if recent_outcomes:
        flood_rate = (
            sum(1 for o in recent_outcomes if o == ExecutionOutcome.FLOOD_WAIT.value)
            / len(recent_outcomes)
        )
    expected_flood = int(round(per_hour * flood_rate))

    if any_ready or remaining_daily == 0:
        best_start_after = 0
    else:
        best_start_after = best_wait or 0

    return ForecastResult(
        expected_primes_per_hour=per_hour,
        expected_flood_per_hour=expected_flood,
        best_start_after=best_start_after,
        sample_size=len(recent_outcomes),
    )


__all__ = [
    "ForecastAccountView",
    "ForecastCampaignView",
    "ForecastResult",
    "compute_forecast",
]
