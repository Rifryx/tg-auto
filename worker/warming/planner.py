"""Планировщик прогрева: выбор действия, окна активности, интервалы (§3, §5).

Окна активности берутся из ``core.config`` (09:00–23:00 в tz по умолчанию — у
аккаунта отдельного tz пока нет). Интервал между действиями — по пресету, с
джиттером ±30%.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.config import Settings, get_settings
from core.enums import WarmingActionType
from worker.warming.presets import JITTER_FRACTION, PRESET_INTERVAL_HOURS

_ACTION_TYPES = list(WarmingActionType)


def choose_action(rng: random.Random) -> WarmingActionType:
    """Случайное действие прогрева."""
    return rng.choice(_ACTION_TYPES)


def is_within_active_window(now: datetime, settings: Settings | None = None) -> bool:
    """Попадает ли ``now`` в окно активности (в tz из конфига)."""
    settings = settings or get_settings()
    try:
        tz = ZoneInfo(settings.default_active_hours_tz)
    except Exception:  # pragma: no cover - на случай отсутствия tzdata
        tz = ZoneInfo("UTC")
    local_time = now.astimezone(tz).timetz().replace(tzinfo=None)
    start = settings.default_active_hours_start
    end = settings.default_active_hours_end
    if start <= end:
        return start <= local_time <= end
    # Окно через полночь (напр. 22:00–06:00).
    return local_time >= start or local_time <= end


def next_interval(profile: str, rng: random.Random) -> timedelta:
    """Интервал до следующего действия: диапазон пресета + джиттер ±30%."""
    low, high = PRESET_INTERVAL_HOURS[profile]
    base_hours = rng.uniform(low, high)
    factor = rng.uniform(1.0 - JITTER_FRACTION, 1.0 + JITTER_FRACTION)
    return timedelta(hours=base_hours * factor)


def due_interval(profile: str) -> timedelta:
    """Порог «пора действовать» для планировщика — нижняя граница пресета."""
    low, _ = PRESET_INTERVAL_HOURS[profile]
    return timedelta(hours=low)
