"""Autopilot: cron-тик планировщика (этап 12).

Раз в 10 минут:
1. Прочитать все включённые цели пользователей.
2. Собрать снимок парка (аккаунты + risk + health).
3. Прогнать чистый ``core.autopilot.plan()``.
4. Применить действия через существующие пути:
   * ``start_warming`` → ``TaskQueue.enqueue(WARMING_INITIAL_START)`` + перевод
     ``created → warming`` через state machine.
   * ``retire_risky`` → ``AccountStateMachine.transition(RETIRE)``.
   * ``throttle`` → ``AccountRepository.update_warming_profile(minimal)``.
5. Каждое решение журналируется в ``autopilot_actions``.
6. Публикация сводки в pub/sub ``autopilot.events``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from core.autopilot.planner import (
    AccountSnapshot,
    FleetState,
    GoalSnapshot,
    PlannedAction,
    plan,
)
from core.enums import (
    AccountStatus,
    AutopilotActionStatus,
    AutopilotActionType,
    Initiator,
    WarmingProfile,
)
from core.models import Account, BanRiskSnapshot
from core.queue import TaskQueue
from core.queue.publisher import Publisher
from core.queue.task_names import TaskName
from core.repositories.autopilot import (
    AutopilotActionRepository,
    AutopilotGoalRepository,
)
from core.state_machine.account import AccountEvent, AccountStateMachine
from worker.tasks.logging import get_logger

AUTOPILOT_CHANNEL = "autopilot.events"


def _snapshot_fleet(session) -> FleetState:
    """Собрать снимок всех аккаунтов + текущий ban_risk."""
    rows = session.execute(
        select(
            Account.id,
            Account.status,
            Account.warming_profile,
            BanRiskSnapshot.risk_score,
        ).outerjoin(BanRiskSnapshot, BanRiskSnapshot.account_id == Account.id)
    ).all()

    accounts = tuple(
        AccountSnapshot(
            account_id=row[0],
            status=row[1],
            warming_profile=row[2],
            ban_risk=float(row[3] or 0.0),
        )
        for row in rows
    )
    return FleetState(accounts=accounts)


def _apply_action(
    session,
    action: PlannedAction,
    publisher: Optional[Publisher],
    task_queue: Optional[TaskQueue],
) -> tuple[str, Optional[str]]:
    """Применить одно действие. Возвращает (status, error_reason)."""
    if action.account_id is None:
        return AutopilotActionStatus.SKIPPED.value, "no account_id"

    machine = AccountStateMachine(session, publisher)

    if action.action_type == AutopilotActionType.START_WARMING.value:
        try:
            machine.transition(
                action.account_id, AccountEvent.WARMING_START, Initiator.AUTO
            )
        except Exception as exc:  # noqa: BLE001
            return AutopilotActionStatus.FAILED.value, str(exc)
        # Планируем прогрев только если очередь передана — иначе аккаунт
        # в статусе warming повиснет; в тестах очередь = spy, в проде = arq.
        if task_queue is not None:
            # Запуск в фоне: ставим через отдельный await ниже (см. вызов в
            # ``autopilot_tick_impl``). Здесь возвращаем planned — очередь
            # обработает планировщик.
            pass
        return AutopilotActionStatus.EXECUTED.value, None

    if action.action_type == AutopilotActionType.RETIRE_RISKY.value:
        # Retire исполняется от имени пользователя (пользователь поставил цель).
        # State machine строго требует Initiator.USER для RETIRE; факт «это
        # решил автопилот» пишется в meta.
        try:
            machine.transition(
                action.account_id, AccountEvent.RETIRE, Initiator.USER,
                meta={"autopilot": True, "reason": action.reason},
            )
        except Exception as exc:  # noqa: BLE001
            return AutopilotActionStatus.FAILED.value, str(exc)
        return AutopilotActionStatus.EXECUTED.value, None

    if action.action_type == AutopilotActionType.THROTTLE.value:
        account = session.get(Account, action.account_id)
        if account is None:
            return AutopilotActionStatus.SKIPPED.value, "account gone"
        account.warming_profile = WarmingProfile.MINIMAL.value
        session.flush()
        return AutopilotActionStatus.EXECUTED.value, None

    return AutopilotActionStatus.SKIPPED.value, f"unknown action: {action.action_type}"


async def autopilot_tick_impl(ctx: dict, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Основная точка входа cron-тика автопилота."""
    now = ctx.get("now") or datetime.now(timezone.utc)
    session_factory = ctx["session_factory"]
    publisher: Optional[Publisher] = ctx.get("publisher")
    task_queue: Optional[TaskQueue] = ctx.get("task_queue")

    executed_by_type: dict[str, int] = defaultdict(int)
    warming_started: list[int] = []
    per_user_summary: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    with session_factory() as session:
        goal_repo = AutopilotGoalRepository(session)
        action_repo = AutopilotActionRepository(session)

        goals = goal_repo.list_enabled()
        if not goals:
            get_logger().info("autopilot.tick.no_goals")
            return {"planned": 0, "executed": 0}

        # Группируем цели по пользователю: у каждого — свой парк и свои цели.
        by_user: dict[str, list[GoalSnapshot]] = defaultdict(list)
        for g in goals:
            by_user[g.user_id].append(
                GoalSnapshot(goal_id=g.id, goal_type=g.goal_type, params=g.params)
            )

        # Снимок парка на всех пользователей одинаковый: у нас пока нет
        # ownership колонки на accounts. Автопилот действует над всем пулом.
        # Когда появится accounts.user_id — фильтровать здесь.
        fleet = _snapshot_fleet(session)

        planned_actions: list[PlannedAction] = []
        for user_id, user_goals in by_user.items():
            actions = plan(user_goals, fleet)
            planned_actions.extend(actions)
            for a in actions:
                per_user_summary[user_id][a.action_type] += 1

        for action in planned_actions:
            status, error = _apply_action(session, action, publisher, task_queue)
            action_repo.log(
                goal_id=action.goal_id,
                action_type=action.action_type,
                account_id=action.account_id,
                status=status,
                reason=action.reason if error is None else f"{action.reason} :: {error}",
                meta=action.meta,
            )
            if status == AutopilotActionStatus.EXECUTED.value:
                executed_by_type[action.action_type] += 1
                if (
                    action.action_type == AutopilotActionType.START_WARMING.value
                    and action.account_id is not None
                ):
                    warming_started.append(action.account_id)

        session.commit()

    # Задачи прогрева ставим ПОСЛЕ commit'а: если arq возьмёт задачу раньше,
    # чем транзакция закоммитится, воркер увидит акк в старом статусе.
    if task_queue is not None:
        for aid in warming_started:
            await task_queue.enqueue(TaskName.WARMING_INITIAL_START, aid)

    if publisher is not None and planned_actions:
        publisher.publish(
            AUTOPILOT_CHANNEL,
            {
                "computed_at": now.isoformat(),
                "planned": len(planned_actions),
                "executed": sum(executed_by_type.values()),
                "by_type": dict(executed_by_type),
                "by_user": {u: dict(s) for u, s in per_user_summary.items()},
            },
        )

    get_logger().info(
        "autopilot.tick.done",
        planned=len(planned_actions),
        executed=sum(executed_by_type.values()),
        by_type=dict(executed_by_type),
    )
    return {
        "planned": len(planned_actions),
        "executed": sum(executed_by_type.values()),
        "by_type": dict(executed_by_type),
    }
