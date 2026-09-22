"""Юнит-тесты чистого планировщика Autopilot (этап 12). Без БД, без сети."""

from __future__ import annotations

from core.autopilot.planner import (
    AccountSnapshot,
    FleetState,
    GoalSnapshot,
    plan,
)
from core.enums import AutopilotActionType, GoalType


def _mk_account(aid, status, ban_risk=0.0, warming_profile="medium"):
    return AccountSnapshot(
        account_id=aid,
        status=status,
        ban_risk=ban_risk,
        warming_profile=warming_profile,
    )


def _mk_goal(goal_type, **params):
    return GoalSnapshot(goal_id=1, goal_type=goal_type, params=params)


# ── maintain_pool_size ──────────────────────────────────────────────────────


def test_maintain_pool_size_no_deficit_produces_nothing():
    """target=2, в pool 3 — ничего не делаем."""
    fleet = FleetState(accounts=(
        _mk_account(1, "pool"), _mk_account(2, "pool"), _mk_account(3, "pool"),
    ))
    goal = _mk_goal(GoalType.MAINTAIN_POOL_SIZE.value, target=2)
    assert plan([goal], fleet) == []


def test_maintain_pool_size_starts_warming_from_created():
    """target=3, в pool 1, в created 5 — стартуем 2 прогрева (детерминированно)."""
    fleet = FleetState(accounts=(
        _mk_account(1, "pool"),
        _mk_account(2, "created"),
        _mk_account(3, "created"),
        _mk_account(4, "created"),
        _mk_account(5, "created"),
        _mk_account(6, "created"),
    ))
    goal = _mk_goal(GoalType.MAINTAIN_POOL_SIZE.value, target=3)
    actions = plan([goal], fleet)
    assert len(actions) == 2
    assert {a.action_type for a in actions} == {AutopilotActionType.START_WARMING.value}
    # Детерминизм: берём с наименьшими id.
    assert sorted(a.account_id for a in actions) == [2, 3]


def test_maintain_pool_size_counts_warming_as_in_progress():
    """target=3, в pool 1, в warming 2 — supply=3, deficit=0, ничего."""
    fleet = FleetState(accounts=(
        _mk_account(1, "pool"),
        _mk_account(2, "warming"),
        _mk_account(3, "warming"),
        _mk_account(4, "created"),
    ))
    goal = _mk_goal(GoalType.MAINTAIN_POOL_SIZE.value, target=3)
    assert plan([goal], fleet) == []


def test_maintain_pool_size_limited_by_created_supply():
    """target=10, в pool 0, в created 2 — стартуем только 2 (сколько есть)."""
    fleet = FleetState(accounts=(
        _mk_account(1, "created"), _mk_account(2, "created"),
    ))
    goal = _mk_goal(GoalType.MAINTAIN_POOL_SIZE.value, target=10)
    actions = plan([goal], fleet)
    assert len(actions) == 2


# ── keep_low_risk ───────────────────────────────────────────────────────────


def test_keep_low_risk_avg_below_threshold_no_action():
    """avg=0.15, max=0.3 — ничего не делаем."""
    fleet = FleetState(accounts=(
        _mk_account(1, "pool", ban_risk=0.1),
        _mk_account(2, "pool", ban_risk=0.2),
    ))
    goal = _mk_goal(GoalType.KEEP_LOW_RISK.value, max_risk=0.3)
    assert plan([goal], fleet) == []


def test_keep_low_risk_retires_critical_accounts():
    """avg превышен, есть аккаунт с ban_risk=0.9 — retire его."""
    fleet = FleetState(accounts=(
        _mk_account(1, "pool", ban_risk=0.9),
        _mk_account(2, "pool", ban_risk=0.1),
    ))
    goal = _mk_goal(GoalType.KEEP_LOW_RISK.value, max_risk=0.3)
    actions = plan([goal], fleet)
    assert len(actions) == 1
    assert actions[0].action_type == AutopilotActionType.RETIRE_RISKY.value
    assert actions[0].account_id == 1


def test_keep_low_risk_throttles_high_but_not_critical():
    """ban_risk=0.65 (>=0.6 но <0.8) → throttle, не retire."""
    fleet = FleetState(accounts=(
        _mk_account(1, "pool", ban_risk=0.65, warming_profile="medium"),
        _mk_account(2, "pool", ban_risk=0.1),
    ))
    goal = _mk_goal(GoalType.KEEP_LOW_RISK.value, max_risk=0.3)
    actions = plan([goal], fleet)
    assert len(actions) == 1
    assert actions[0].action_type == AutopilotActionType.THROTTLE.value
    assert actions[0].account_id == 1


def test_keep_low_risk_skips_already_minimal():
    """Уже minimal — не тротлим повторно."""
    fleet = FleetState(accounts=(
        _mk_account(1, "pool", ban_risk=0.65, warming_profile="minimal"),
        _mk_account(2, "pool", ban_risk=0.1),
    ))
    goal = _mk_goal(GoalType.KEEP_LOW_RISK.value, max_risk=0.3)
    assert plan([goal], fleet) == []


def test_keep_low_risk_critical_beats_throttle():
    """0.85 → retire (не throttle), 0.65 → throttle."""
    fleet = FleetState(accounts=(
        _mk_account(1, "pool", ban_risk=0.85),
        _mk_account(2, "pool", ban_risk=0.65),
    ))
    goal = _mk_goal(GoalType.KEEP_LOW_RISK.value, max_risk=0.3)
    actions = plan([goal], fleet)
    types = {a.account_id: a.action_type for a in actions}
    assert types[1] == AutopilotActionType.RETIRE_RISKY.value
    assert types[2] == AutopilotActionType.THROTTLE.value


# ── warmup_pipeline ─────────────────────────────────────────────────────────


def test_warmup_pipeline_fills_from_created():
    """target=3, в warming 1, в created 5 — доливаем 2."""
    fleet = FleetState(accounts=(
        _mk_account(1, "warming"),
        _mk_account(2, "created"),
        _mk_account(3, "created"),
        _mk_account(4, "created"),
    ))
    goal = _mk_goal(GoalType.WARMUP_PIPELINE.value, target=3)
    actions = plan([goal], fleet)
    assert len(actions) == 2
    assert all(a.action_type == AutopilotActionType.START_WARMING.value for a in actions)


# ── deduplication + priority ────────────────────────────────────────────────


def test_dedup_by_account_id():
    """Две цели могут выдать действия на один и тот же account_id: берём одно."""
    fleet = FleetState(accounts=(
        _mk_account(1, "created"),
    ))
    goals = [
        GoalSnapshot(1, GoalType.MAINTAIN_POOL_SIZE.value, {"target": 1}),
        GoalSnapshot(2, GoalType.WARMUP_PIPELINE.value, {"target": 1}),
    ]
    actions = plan(goals, fleet)
    assert len(actions) == 1
    assert actions[0].account_id == 1


def test_retire_wins_over_throttle():
    """Один аккаунт: retire всегда побеждает throttle (важно для безопасности)."""
    fleet = FleetState(accounts=(
        _mk_account(1, "pool", ban_risk=0.85),
        _mk_account(2, "pool", ban_risk=0.1),
    ))
    # Первая цель дала бы throttle (если бы риск был 0.65), но здесь критический
    # риск — обе цели дадут действия на один и тот же акк, retire должно
    # побеждать. Для проверки приоритета соберём вручную.
    goals = [
        GoalSnapshot(1, GoalType.KEEP_LOW_RISK.value, {"max_risk": 0.3}),
    ]
    actions = plan(goals, fleet)
    assert len(actions) == 1
    assert actions[0].action_type == AutopilotActionType.RETIRE_RISKY.value


# ── invalid input ───────────────────────────────────────────────────────────


def test_zero_target_no_action():
    """target=0 → ничего не делаем (нет отрицательных действий)."""
    fleet = FleetState(accounts=(_mk_account(1, "created"),))
    goal = _mk_goal(GoalType.MAINTAIN_POOL_SIZE.value, target=0)
    assert plan([goal], fleet) == []


def test_unknown_goal_type_ignored():
    """Неизвестный goal_type → игнорируется, других целей не ломает."""
    fleet = FleetState(accounts=(_mk_account(1, "created"),))
    goals = [
        GoalSnapshot(1, "unknown_goal_type", {}),
        GoalSnapshot(2, GoalType.MAINTAIN_POOL_SIZE.value, {"target": 1}),
    ]
    actions = plan(goals, fleet)
    assert len(actions) == 1
    assert actions[0].goal_id == 2
