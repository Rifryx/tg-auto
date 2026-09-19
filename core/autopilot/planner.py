"""Чистый планировщик автопилота (этап 12).

Функция ``plan(goals, state)`` не имеет побочных эффектов: принимает цели и
снимок парка, возвращает список запланированных действий. Все обращения к БД,
Redis и очереди задач — в вызывающем таск-обработчике (``worker/tasks/autopilot.py``).

Такая же архитектура, как у ``core.predictor.predict_risk``: чистая функция
проще тестируется и не зависит от инфраструктуры.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from core.enums import AccountStatus, AutopilotActionType, GoalType


@dataclass(frozen=True)
class AccountSnapshot:
    """Один аккаунт как видит его планировщик."""

    account_id: int
    status: str
    ban_risk: float = 0.0
    health_score: int = 100
    warming_profile: Optional[str] = None


@dataclass(frozen=True)
class GoalSnapshot:
    """Цель + её параметры для планировщика."""

    goal_id: int
    goal_type: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FleetState:
    """Снимок парка аккаунтов для одного пользователя."""

    accounts: tuple[AccountSnapshot, ...]

    def by_status(self, status: str) -> list[AccountSnapshot]:
        return [a for a in self.accounts if a.status == status]

    def average_risk(self) -> float:
        active = [
            a for a in self.accounts
            if a.status in (
                AccountStatus.POOL.value,
                AccountStatus.ASSIGNED.value,
                AccountStatus.WARMING.value,
            )
        ]
        if not active:
            return 0.0
        return sum(a.ban_risk for a in active) / len(active)


@dataclass(frozen=True)
class PlannedAction:
    """Действие, которое планировщик хочет применить."""

    goal_id: int
    action_type: str
    account_id: Optional[int]
    reason: str
    meta: dict[str, Any] = field(default_factory=dict)


# ── пороги (rule-based, как в Predictor) ────────────────────────────────────

# Порог риска, выше которого аккаунт считается «слишком опасным для работы».
_CRITICAL_RISK_THRESHOLD = 0.8
# Порог для «сбавить темп» (throttle → minimal profile).
_HIGH_RISK_THRESHOLD = 0.6
# Сколько действий на один tick максимум (защита от бури enqueue).
_MAX_ACTIONS_PER_GOAL = 10


def _plan_maintain_pool_size(goal: GoalSnapshot, state: FleetState) -> list[PlannedAction]:
    """Держать не меньше ``target`` аккаунтов в pool.

    Если недобор — брать из `created` и стартовать прогрев. `warming` уже в пути
    к pool, так что учитываем их как «идут». Не создаём новые аккаунты — только
    двигаем существующие.
    """
    target = int(goal.params.get("target", 0))
    if target <= 0:
        return []

    in_pool = state.by_status(AccountStatus.POOL.value)
    in_warming = state.by_status(AccountStatus.WARMING.value)
    supply_in_progress = len(in_pool) + len(in_warming)
    deficit = target - supply_in_progress
    if deficit <= 0:
        return []

    # Кандидаты — только `created` (готовые к прогреву). Сортируем по account_id
    # для детерминизма (без него порядок из БД плавает).
    candidates = sorted(
        state.by_status(AccountStatus.CREATED.value),
        key=lambda a: a.account_id,
    )
    take = min(deficit, len(candidates), _MAX_ACTIONS_PER_GOAL)
    return [
        PlannedAction(
            goal_id=goal.goal_id,
            action_type=AutopilotActionType.START_WARMING.value,
            account_id=a.account_id,
            reason=(
                f"pool deficit: have {supply_in_progress}, need {target}"
            ),
            meta={"target": target, "current_supply": supply_in_progress},
        )
        for a in candidates[:take]
    ]


def _plan_keep_low_risk(goal: GoalSnapshot, state: FleetState) -> list[PlannedAction]:
    """Держать средний ban_risk ниже порога.

    Если средний risk выше ``max_risk`` — retire критически рискованных
    (>= 0.8) и throttle сильно рискованных (>= 0.6). Здоровые аккаунты не
    трогаем: цель не «убить всех», а понизить среднее.
    """
    max_risk = float(goal.params.get("max_risk", 0.3))
    avg = state.average_risk()
    if avg <= max_risk:
        return []

    actions: list[PlannedAction] = []
    # Сначала retire самых опасных (критический риск): чтобы средний упал быстро.
    critical = sorted(
        (a for a in state.accounts if a.ban_risk >= _CRITICAL_RISK_THRESHOLD),
        key=lambda a: -a.ban_risk,
    )
    for a in critical[:_MAX_ACTIONS_PER_GOAL]:
        actions.append(PlannedAction(
            goal_id=goal.goal_id,
            action_type=AutopilotActionType.RETIRE_RISKY.value,
            account_id=a.account_id,
            reason=f"critical ban_risk={a.ban_risk:.2f} (avg={avg:.2f} > {max_risk})",
            meta={"ban_risk": a.ban_risk, "avg_risk": avg},
        ))

    remaining = _MAX_ACTIONS_PER_GOAL - len(actions)
    if remaining <= 0:
        return actions

    # Затем throttle «просто высоких» (не критических): им опустим темп прогрева.
    high = sorted(
        (
            a for a in state.accounts
            if _HIGH_RISK_THRESHOLD <= a.ban_risk < _CRITICAL_RISK_THRESHOLD
            and a.warming_profile != "minimal"
        ),
        key=lambda a: -a.ban_risk,
    )
    for a in high[:remaining]:
        actions.append(PlannedAction(
            goal_id=goal.goal_id,
            action_type=AutopilotActionType.THROTTLE.value,
            account_id=a.account_id,
            reason=f"high ban_risk={a.ban_risk:.2f}, throttle to minimal",
            meta={"ban_risk": a.ban_risk, "from_profile": a.warming_profile},
        ))
    return actions


def _plan_warmup_pipeline(goal: GoalSnapshot, state: FleetState) -> list[PlannedAction]:
    """Держать не меньше ``target`` аккаунтов одновременно в warming.

    Если warming меньше target — доливаем из `created` (сколько есть).
    """
    target = int(goal.params.get("target", 0))
    if target <= 0:
        return []

    in_warming = state.by_status(AccountStatus.WARMING.value)
    deficit = target - len(in_warming)
    if deficit <= 0:
        return []

    candidates = sorted(
        state.by_status(AccountStatus.CREATED.value),
        key=lambda a: a.account_id,
    )
    take = min(deficit, len(candidates), _MAX_ACTIONS_PER_GOAL)
    return [
        PlannedAction(
            goal_id=goal.goal_id,
            action_type=AutopilotActionType.START_WARMING.value,
            account_id=a.account_id,
            reason=(
                f"warmup pipeline: have {len(in_warming)}, need {target}"
            ),
            meta={"target": target, "current": len(in_warming)},
        )
        for a in candidates[:take]
    ]


_PLANNERS = {
    GoalType.MAINTAIN_POOL_SIZE.value: _plan_maintain_pool_size,
    GoalType.KEEP_LOW_RISK.value: _plan_keep_low_risk,
    GoalType.WARMUP_PIPELINE.value: _plan_warmup_pipeline,
}


def plan(goals: list[GoalSnapshot], state: FleetState) -> list[PlannedAction]:
    """Основной вход. Возвращает объединённый список действий по всем целям.

    Дедупликация: если одному аккаунту разные цели присвоили разные действия,
    сохраняем то, что появилось первым (порядок целей = порядок в списке).
    Retire побеждает throttle/start_warming: retire безусловно финальный.
    """
    raw: list[PlannedAction] = []
    for goal in goals:
        planner_fn = _PLANNERS.get(goal.goal_type)
        if planner_fn is None:
            continue
        raw.extend(planner_fn(goal, state))

    seen: dict[int, PlannedAction] = {}
    for action in raw:
        if action.account_id is None:
            continue
        existing = seen.get(action.account_id)
        if existing is None:
            seen[action.account_id] = action
            continue
        # retire всегда побеждает: акк который надо вывести — не должен
        # получать start_warming или throttle параллельно.
        if action.action_type == AutopilotActionType.RETIRE_RISKY.value:
            seen[action.account_id] = action
    return list(seen.values())
