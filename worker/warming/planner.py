"""Планировщик прогрева: выбор действия, окна активности, интервалы.

Этап 10 УТП добавил персонализацию: у ``Persona`` может быть свой tz, своё
окно активности и веса действий из ``personality_tags``. Health Score
адаптирует темп — низкий score удлиняет интервал и урезает вероятность
«агрессивных» действий (subscribe/join_group).

Все функции — чистые: принимают опциональную персону/score, при их отсутствии
поведение совпадает с прежним (config-based).
"""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from core.config import Settings, get_settings
from core.enums import WarmingActionType
from worker.warming.presets import JITTER_FRACTION, PRESET_INTERVAL_HOURS

_ACTION_TYPES = list(WarmingActionType)

# «Агрессивные» действия — те, что оставляют след у Telegram (подписка,
# вступление). Их вклад в веса урезается для низкого Health Score.
_AGGRESSIVE_ACTIONS = frozenset(
    {WarmingActionType.SUBSCRIBE_CHANNEL, WarmingActionType.JOIN_GROUP}
)

# Базовые веса по тегам персоны. Формат: tag → {action: multiplier}. Отсутствие
# тега = дефолтные веса (все 1.0). ``formal`` меньше реагирует и не спамит
# джойнами; ``casual`` — наоборот; ``lurker`` фокусируется на чтении/idle.
_TAG_WEIGHTS: dict[str, dict[WarmingActionType, float]] = {
    "formal": {
        WarmingActionType.REACTION: 0.4,
        WarmingActionType.IDLE_ONLINE: 1.3,
        WarmingActionType.JOIN_GROUP: 0.5,
    },
    "casual": {
        WarmingActionType.REACTION: 1.6,
        WarmingActionType.SUBSCRIBE_CHANNEL: 1.4,
    },
    "lurker": {
        WarmingActionType.READ_HISTORY: 2.0,
        WarmingActionType.VIEW_MEDIA: 1.8,
        WarmingActionType.IDLE_ONLINE: 1.5,
        WarmingActionType.JOIN_GROUP: 0.2,
        WarmingActionType.SUBSCRIBE_CHANNEL: 0.3,
        WarmingActionType.REACTION: 0.4,
    },
}


def choose_action(
    rng: random.Random,
    persona=None,
    *,
    health_score: Optional[int] = None,
) -> WarmingActionType:
    """Взвешенный случайный выбор действия по тегам персоны и Health Score.

    Без ``persona`` и ``health_score`` — равномерное распределение (обратная
    совместимость с прежним unif-random выбором).
    """
    weights = _compute_weights(persona, health_score)
    return rng.choices(_ACTION_TYPES, weights=weights, k=1)[0]


def _compute_weights(persona, health_score: Optional[int]) -> list[float]:
    weights = {a: 1.0 for a in _ACTION_TYPES}
    tags = list(getattr(persona, "personality_tags", None) or []) if persona else []
    for tag in tags:
        multipliers = _TAG_WEIGHTS.get(tag)
        if not multipliers:
            continue
        for action, mult in multipliers.items():
            weights[action] *= mult
    # Низкий Health Score — гасим агрессивные действия и подкачиваем idle.
    if health_score is not None and health_score < 40:
        for action in _AGGRESSIVE_ACTIONS:
            weights[action] *= 0.25
        weights[WarmingActionType.IDLE_ONLINE] *= 1.5
    return [weights[a] for a in _ACTION_TYPES]


def is_within_active_window(
    now: datetime, settings: Settings | None = None, persona=None
) -> bool:
    """Попадает ли ``now`` в окно активности.

    Если у ``persona`` есть свои ``timezone`` / ``active_hours_start`` /
    ``active_hours_end`` — берём их (это делает акки «жителями» своих часовых
    поясов и естественно распределяет активность по суткам). Иначе фолбэк на
    глобальный config.
    """
    settings = settings or get_settings()
    tz_name, start, end = _window(persona, settings)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # pragma: no cover
        tz = ZoneInfo("UTC")
    local_time = now.astimezone(tz).timetz().replace(tzinfo=None)
    if start <= end:
        return start <= local_time <= end
    # Окно через полночь (напр. 22:00–06:00).
    return local_time >= start or local_time <= end


def _window(persona, settings: Settings) -> tuple[str, time, time]:
    tz = getattr(persona, "timezone", None) if persona else None
    start = getattr(persona, "active_hours_start", None) if persona else None
    end = getattr(persona, "active_hours_end", None) if persona else None
    return (
        tz or settings.default_active_hours_tz,
        start or settings.default_active_hours_start,
        end or settings.default_active_hours_end,
    )


def next_interval(
    profile: str, rng: random.Random, *, health_score: Optional[int] = None
) -> timedelta:
    """Интервал до следующего действия: диапазон пресета + джиттер ±30%.

    ``health_score``: <40 → х2 (замедляем прогрев рискованного акка). >=71 →
    без изменений (акк здоров, не тормозим).
    """
    low, high = PRESET_INTERVAL_HOURS[profile]
    base_hours = rng.uniform(low, high)
    factor = rng.uniform(1.0 - JITTER_FRACTION, 1.0 + JITTER_FRACTION)
    multiplier = 2.0 if (health_score is not None and health_score < 40) else 1.0
    return timedelta(hours=base_hours * factor * multiplier)


def due_interval(
    profile: str, *, health_score: Optional[int] = None
) -> timedelta:
    """Порог «пора действовать» для планировщика — нижняя граница пресета.

    Аналогично ``next_interval``: score < 40 удваивает нижнюю границу, чтобы
    at-risk аккаунты чаще попадали в skip, чем в tick.
    """
    low, _ = PRESET_INTERVAL_HOURS[profile]
    multiplier = 2.0 if (health_score is not None and health_score < 40) else 1.0
    return timedelta(hours=low * multiplier)
