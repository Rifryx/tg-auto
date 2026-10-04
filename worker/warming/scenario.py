"""Кастомный сценарий прогрева («Конструктор сценариев», карточка аккаунта).

До сих пор темп прогрева задавался только пресетом (minimal/medium/dense) —
см. :mod:`worker.warming.presets`. Сценарий позволяет переопределить на уровне
аккаунта: интервал между действиями, размер стартовой пачки, микс действий
(веса; 0 = действие выключено) и критерий готовности warming→pool.

Хранится в ``accounts.meta['warming_scenario']`` (без отдельной таблицы/миграции).
Отсутствие сценария → поведение ровно как раньше (фолбэк на пресет). Парсинг
защитный: битые значения игнорируются, не роняя воркер.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.enums import WarmingActionType

META_KEY = "warming_scenario"

_ACTION_VALUES = {a.value for a in WarmingActionType}


@dataclass
class WarmingScenario:
    interval_hours: Optional[tuple[float, float]] = None
    actions_per_batch: Optional[tuple[int, int]] = None
    # action_value -> weight (>=0). 0 = выключено. Отсутствующие действия = 0,
    # если словарь задан (т.е. явный белый список).
    action_weights: Optional[dict[str, float]] = None
    ready_actions: Optional[int] = None
    ready_days: Optional[int] = None

    def is_empty(self) -> bool:
        return (
            self.interval_hours is None
            and self.actions_per_batch is None
            and not self.action_weights
            and self.ready_actions is None
            and self.ready_days is None
        )

    @classmethod
    def from_meta(cls, meta: Optional[dict]) -> Optional["WarmingScenario"]:
        """Достаёт сценарий из ``account.meta``; None — если не задан/битый."""
        if not meta:
            return None
        raw = meta.get(META_KEY)
        if not isinstance(raw, dict):
            return None
        sc = cls(
            interval_hours=_pair_float(raw.get("interval_hours")),
            actions_per_batch=_pair_int(raw.get("actions_per_batch")),
            action_weights=_weights(raw.get("action_weights")),
            ready_actions=_pos_int(raw.get("ready_actions")),
            ready_days=_pos_int(raw.get("ready_days")),
        )
        return None if sc.is_empty() else sc


def _pair_float(v) -> Optional[tuple[float, float]]:
    try:
        lo, hi = float(v[0]), float(v[1])
    except (TypeError, ValueError, IndexError):
        return None
    if lo <= 0 or hi < lo:
        return None
    return (lo, hi)


def _pair_int(v) -> Optional[tuple[int, int]]:
    try:
        lo, hi = int(v[0]), int(v[1])
    except (TypeError, ValueError, IndexError):
        return None
    if lo < 1 or hi < lo:
        return None
    return (lo, hi)


def _weights(v) -> Optional[dict[str, float]]:
    if not isinstance(v, dict):
        return None
    out: dict[str, float] = {}
    for key, val in v.items():
        if key not in _ACTION_VALUES:
            continue
        try:
            w = float(val)
        except (TypeError, ValueError):
            continue
        if w >= 0:
            out[key] = w
    return out or None


def _pos_int(v) -> Optional[int]:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None
