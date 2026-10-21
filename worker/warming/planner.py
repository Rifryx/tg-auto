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
from worker.warming.presets import (
    JITTER_FRACTION,
    PRESET_ACTION_COUNT,
    PRESET_INTERVAL_HOURS,
)
from worker.warming.scenario import WarmingScenario

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
    scenario: Optional[WarmingScenario] = None,
) -> WarmingActionType:
    """Взвешенный случайный выбор действия по тегам персоны и риску.

    Без ``persona`` и ``health_score``/``ban_risk`` — равномерное распределение
    (обратная совместимость с прежним unif-random выбором). ``scenario`` задаёт
    базовый микс действий (белый список с весами; 0 = выключено), поверх которого
    всё так же применяются множители персоны и риска.
    """
    weights = _compute_weights(persona, health_score, ban_risk, scenario)
    # По умолчанию прогрев НЕ авто-подписывается на каналы и не вступает в группы:
    # цели берутся из случайного каталога (DISCOVERY_CHANNELS), а не из ссылок
    # пользователя — лишний след у Telegram. Включается ТОЛЬКО если сценарий
    # прогрева явно задал вес для этих действий (ручная настройка) или
    # WARMING_AUTO_SUBSCRIBE=true в окружении.
    if not _auto_joins_enabled(scenario):
        for at in (WarmingActionType.SUBSCRIBE_CHANNEL, WarmingActionType.JOIN_GROUP):
            weights[_ACTION_TYPES.index(at)] = 0.0
    if sum(weights) <= 0:  # защита: если вдруг всё обнулилось
        weights = [1.0] * len(_ACTION_TYPES)
    return rng.choices(_ACTION_TYPES, weights=weights, k=1)[0]


def _auto_joins_enabled(scenario: Optional[WarmingScenario]) -> bool:
    """Разрешены ли авто-подписки/вступления в прогреве.

    Да, если: (а) сценарий ЯВНО задал положительный вес SUBSCRIBE_CHANNEL или
    JOIN_GROUP (пользователь настроил вручную), либо (б) включён флаг окружения
    ``WARMING_AUTO_SUBSCRIBE``. Иначе — нет (поведение по умолчанию).
    """
    if scenario is not None and scenario.action_weights:
        for key in (
            WarmingActionType.SUBSCRIBE_CHANNEL.value,
            WarmingActionType.JOIN_GROUP.value,
        ):
            if scenario.action_weights.get(key, 0) and scenario.action_weights[key] > 0:
                return True
    try:
        return bool(getattr(get_settings(), "warming_auto_subscribe", False))
    except Exception:  # noqa: BLE001 — настройки недоступны → по умолчанию выкл
        return False


def _compute_weights(
    persona,
    health_score: Optional[int],
    ban_risk: Optional[float] = None,
    scenario: Optional[WarmingScenario] = None,
) -> list[float]:
    # База: из сценария (явный белый список, unlisted=0) либо все 1.0.
    if scenario is not None and scenario.action_weights:
        weights = {a: scenario.action_weights.get(a.value, 0.0) for a in _ACTION_TYPES}
        if sum(weights.values()) <= 0:  # защита от all-zero → равномерно
            weights = {a: 1.0 for a in _ACTION_TYPES}
    else:
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
    now: datetime,
    settings: Settings | None = None,
    persona=None,
    defaults: dict | None = None,
) -> bool:
    """Попадает ли ``now`` в окно активности.

    Приоритет источников окна/таймзоны:
    1) собственные поля персоны (``timezone`` / ``active_hours_*``) — акки
       «живут» в своих часовых поясах;
    2) ``defaults`` — настройки активности пользователя (таймзона + окно),
       сохранённые в Settings, если переданы;
    3) глобальный env-config как последний фолбэк.
    """
    settings = settings or get_settings()
    tz_name, start, end = _window(persona, settings, defaults)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # pragma: no cover
        tz = ZoneInfo("UTC")
    local_time = now.astimezone(tz).timetz().replace(tzinfo=None)
    if start <= end:
        return start <= local_time <= end
    # Окно через полночь (напр. 22:00–06:00).
    return local_time >= start or local_time <= end


def _parse_hhmm(value, fallback: time) -> time:
    """'HH:MM' → time; при ошибке — fallback."""
    if isinstance(value, time):
        return value
    if isinstance(value, str) and ":" in value:
        try:
            h, m = value.split(":", 1)
            return time(int(h), int(m))
        except (ValueError, TypeError):
            return fallback
    return fallback


def _window(persona, settings: Settings, defaults: dict | None = None) -> tuple[str, time, time]:
    tz = getattr(persona, "timezone", None) if persona else None
    start = getattr(persona, "active_hours_start", None) if persona else None
    end = getattr(persona, "active_hours_end", None) if persona else None
    defaults = defaults or {}
    default_tz = defaults.get("timezone") or settings.default_active_hours_tz
    default_start = (
        _parse_hhmm(defaults.get("window_start"), settings.default_active_hours_start)
        if defaults.get("window_start")
        else settings.default_active_hours_start
    )
    default_end = (
        _parse_hhmm(defaults.get("window_end"), settings.default_active_hours_end)
        if defaults.get("window_end")
        else settings.default_active_hours_end
    )
    return (
        tz or default_tz,
        start or default_start,
        end or default_end,
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


def _interval_range(
    profile: str, scenario: Optional[WarmingScenario]
) -> tuple[float, float]:
    """Диапазон интервала: из сценария, иначе из пресета."""
    if scenario is not None and scenario.interval_hours is not None:
        return scenario.interval_hours
    return PRESET_INTERVAL_HOURS[profile]


def next_interval(
    profile: str,
    rng: random.Random,
    *,
    health_score: Optional[int] = None,
    ban_risk: Optional[float] = None,
    scenario: Optional[WarmingScenario] = None,
) -> timedelta:
    """Интервал до следующего действия: диапазон пресета/сценария + джиттер ±30%.

    ``ban_risk`` (этап 11): плавное замедление пропорционально риску бана.
    Fallback на ``health_score`` < 40 → x2.
    """
    low, high = _interval_range(profile, scenario)
    base_hours = rng.uniform(low, high)
    factor = rng.uniform(1.0 - JITTER_FRACTION, 1.0 + JITTER_FRACTION)
    multiplier = _risk_multiplier(health_score, ban_risk)
    return timedelta(hours=base_hours * factor * multiplier)


def due_interval(
    profile: str,
    *,
    health_score: Optional[int] = None,
    ban_risk: Optional[float] = None,
    scenario: Optional[WarmingScenario] = None,
) -> timedelta:
    """Порог «пора действовать» — нижняя граница пресета/сценария.

    Аналогично ``next_interval``: ban_risk плавно увеличивает порог.
    """
    low, _ = _interval_range(profile, scenario)
    multiplier = _risk_multiplier(health_score, ban_risk)
    return timedelta(hours=low * multiplier)


def batch_action_count(
    profile: str,
    rng: random.Random,
    *,
    scenario: Optional[WarmingScenario] = None,
) -> int:
    """Размер пачки действий: из сценария, иначе из пресета."""
    if scenario is not None and scenario.actions_per_batch is not None:
        low, high = scenario.actions_per_batch
    else:
        low, high = PRESET_ACTION_COUNT[profile]
    return rng.randint(low, high)
