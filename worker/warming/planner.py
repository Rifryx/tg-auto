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
        # Одиночка не тусит с peer'ами:
        WarmingActionType.INTERACT_WITH_PEER: 0.3,
    },
    # Trust-graph (этап 10, backlog #2): «социальные» персоны чаще общаются
    # с peer'ами того же проекта/команды.
    "social": {
        WarmingActionType.INTERACT_WITH_PEER: 2.5,
        WarmingActionType.REACTION: 1.3,
    },
}


def choose_action(
    rng: random.Random,
    persona=None,
    *,
    health_score: Optional[int] = None,
    ban_risk: Optional[float] = None,
) -> WarmingActionType:
    """Взвешенный случайный выбор действия по тегам персоны и риску.

    Без ``persona`` и ``health_score``/``ban_risk`` — равномерное распределение
    (обратная совместимость с прежним unif-random выбором).
    """
    weights = _compute_weights(persona, health_score, ban_risk)
    return rng.choices(_ACTION_TYPES, weights=weights, k=1)[0]


def _compute_weights(
    persona, health_score: Optional[int], ban_risk: Optional[float] = None
) -> list[float]:
    weights = {a: 1.0 for a in _ACTION_TYPES}
    tags = list(getattr(persona, "personality_tags", None) or []) if persona else []
    for tag in tags:
        multipliers = _TAG_WEIGHTS.get(tag)
        if not multipliers:
            continue
        for action, mult in multipliers.items():
            weights[action] *= mult

    # Anti-Ban Predictor: непрерывная модуляция по ban_risk (этап 11).
    # ban_risk даёт более гранулярную адаптацию, чем бинарный health_score < 40.
    if ban_risk is not None and ban_risk > 0.2:
        # Линейное ослабление агрессивных действий: risk 0.2→1.0 = mult 0.8→0.05.
        aggressive_mult = max(0.05, 1.0 - ban_risk)
        idle_mult = 1.0 + ban_risk
        for action in _AGGRESSIVE_ACTIONS:
            weights[action] *= aggressive_mult
        weights[WarmingActionType.IDLE_ONLINE] *= idle_mult
    elif health_score is not None and health_score < 40:
        # Fallback на бинарный health_score, если ban_risk ещё не рассчитан.
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


def _risk_multiplier(
    health_score: Optional[int] = None,
    ban_risk: Optional[float] = None,
) -> float:
    """Вычисляет множитель замедления по ban_risk или health_score.

    ban_risk (непрерывный, 0–1) имеет приоритет: даёт плавное замедление
    1.0x при risk=0 → 3.0x при risk=1.0. Fallback на бинарный health_score.
    """
    if ban_risk is not None and ban_risk > 0.2:
        return 1.0 + ban_risk * 2.5  # 0.2→1.5x, 0.5→2.25x, 1.0→3.5x
    if health_score is not None and health_score < 40:
        return 2.0
    return 1.0


def next_interval(
    profile: str,
    rng: random.Random,
    *,
    health_score: Optional[int] = None,
    ban_risk: Optional[float] = None,
) -> timedelta:
    """Интервал до следующего действия: диапазон пресета + джиттер ±30%.

    ``ban_risk`` (этап 11): плавное замедление пропорционально риску бана.
    Fallback на ``health_score`` < 40 → x2.
    """
    low, high = PRESET_INTERVAL_HOURS[profile]
    base_hours = rng.uniform(low, high)
    factor = rng.uniform(1.0 - JITTER_FRACTION, 1.0 + JITTER_FRACTION)
    multiplier = _risk_multiplier(health_score, ban_risk)
    return timedelta(hours=base_hours * factor * multiplier)


def due_interval(
    profile: str,
    *,
    health_score: Optional[int] = None,
    ban_risk: Optional[float] = None,
) -> timedelta:
    """Порог «пора действовать» для планировщика — нижняя граница пресета.

    Аналогично ``next_interval``: ban_risk плавно увеличивает порог.
    """
    low, _ = PRESET_INTERVAL_HOURS[profile]
    multiplier = _risk_multiplier(health_score, ban_risk)
    return timedelta(hours=low * multiplier)
