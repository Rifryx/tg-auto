"""Тела задач прогрева (PROJECT-STAGES §3, §5).

Движок и планировщик живут в ``worker/warming``; здесь — оркестрация задач:
получить клиента через :class:`ClientPool`, выбрать и выполнить действие,
записать :class:`WarmingActivity`, отпустить клиента. Смена статуса — только
через :class:`AccountStateMachine`.

``now`` и ``rng`` берутся из ``ctx`` при наличии — это точки инъекции для
детерминированных тестов (fake clock / seeded RNG).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select

from core.enums import (
    AccountStatus,
    Initiator,
    WarmingActivityKind,
    WarmingActivityStatus,
)
from core.models import HealthEvent, WarmingActivity
from core.queue import TaskQueue
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from core.repositories.warming_activity import WarmingActivityRepository
from core.schemas.warming import WarmingActivityCreate
from core.state_machine import AccountEvent, AccountStateMachine
from worker.client_pool import ClientPool
from worker.health import Governor
from worker.tasks.logging import get_logger
from worker.warming.actions import execute_action
from worker.warming.planner import choose_action, due_interval, is_within_active_window
from worker.warming.presets import (
    INITIAL_BATCH_PROFILE,
    PRESET_ACTION_COUNT,
    WARMING_READY_ACTIONS,
    WARMING_READY_DAYS,
)

_ACTIVE_WARMING_STATUSES = (AccountStatus.WARMING.value, AccountStatus.POOL.value)


def _now(ctx: dict) -> datetime:
    return ctx.get("now") or datetime.now(timezone.utc)


def _rng(ctx: dict) -> random.Random:
    return ctx.get("rng") or random.Random()


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


def _task_queue(ctx: dict) -> TaskQueue:
    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


def _governor(ctx: dict) -> Governor:
    return ctx.get("governor") or Governor(ctx.get("redis"))


def _successful_initial_actions(session, account_id: int) -> int:
    return session.execute(
        select(func.count())
        .select_from(WarmingActivity)
        .where(
            WarmingActivity.account_id == account_id,
            WarmingActivity.kind == WarmingActivityKind.INITIAL.value,
            WarmingActivity.status == WarmingActivityStatus.DONE.value,
        )
    ).scalar_one()


def _unresolved_incidents(session, account_id: int) -> int:
    return session.execute(
        select(func.count())
        .select_from(HealthEvent)
        .where(HealthEvent.account_id == account_id, HealthEvent.resolved.is_(False))
    ).scalar_one()


def _maybe_complete_warming(session, publisher, account_id: int, now: datetime) -> bool:
    """Если аккаунт готов (§3): warming → pool через state machine.

    Критерий: (>= WARMING_READY_ACTIONS успешных initial-действий) ИЛИ (>=
    WARMING_READY_DAYS в прогреве) И отсутствие неразрешённых health-инцидентов.
    """
    if _unresolved_incidents(session, account_id) > 0:
        return False
    account = AccountRepository(session).get(account_id)
    if account is None or account.status != AccountStatus.WARMING.value:
        return False
    done = _successful_initial_actions(session, account_id)
    age_ok = (
        account.warming_started_at is not None
        and (now - account.warming_started_at) >= timedelta(days=WARMING_READY_DAYS)
    )
    if done >= WARMING_READY_ACTIONS or age_ok:
        AccountStateMachine(session, publisher).transition(
            account_id, AccountEvent.WARMING_COMPLETED, Initiator.AUTO
        )
        return True
    return False


async def warming_tick_impl(ctx: dict, account_id: int) -> Optional[str]:
    """Одно действие прогрева: get client → выбрать → выполнить → записать."""
    now = _now(ctx)
    rng = _rng(ctx)
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    log = get_logger()

    with session_factory() as session:
        account = AccountRepository(session).get(account_id)
        if account is None:
            log.warning("warming.tick.no_account", account_id=account_id)
            return None
        status = account.status

    if status not in _ACTIVE_WARMING_STATUSES:
        log.info("warming.tick.skipped", account_id=account_id, reason="status", status=status)
        return "skipped"

    if not is_within_active_window(now):
        # Вне окна активности действие не выполняется и НЕ записывается (§3).
        log.info("warming.tick.skipped", account_id=account_id, reason="inactive_window")
        return "skipped"

    kind = (
        WarmingActivityKind.INITIAL
        if status == AccountStatus.WARMING.value
        else WarmingActivityKind.MAINTENANCE
    )
    action_type = choose_action(rng)

    pool = _pool(ctx)
    client = await pool.get(account_id)
    try:
        result = await execute_action(
            action_type,
            client,
            account,
            governor=_governor(ctx),
            session_factory=session_factory,
            publisher=publisher,
            now=now,
        )
    finally:
        await pool.release(account_id)

    with session_factory() as session:
        WarmingActivityRepository(session).create(
            WarmingActivityCreate(
                account_id=account_id,
                kind=kind,
                action_type=result.action_type,
                status=result.status,
                target=result.target,
                meta=result.meta,
            )
        )
        session.commit()
        if kind is WarmingActivityKind.INITIAL:
            _maybe_complete_warming(session, publisher, account_id, now)

    log.info(
        "warming.tick.done",
        account_id=account_id,
        action=result.action_type.value,
        status=result.status.value,
        kind=kind.value,
    )
    return result.status.value


async def maintenance_scheduler_impl(ctx: dict, *args: Any, **kwargs: Any) -> list[int]:
    """Cron (каждые 5 мин): для аккаунтов в pool планирует warming.tick по сроку."""
    now = _now(ctx)
    session_factory = ctx["session_factory"]
    task_queue = _task_queue(ctx)

    due: list[int] = []
    with session_factory() as session:
        accounts = AccountRepository(session).list_by_status(AccountStatus.POOL)
        wa_repo = WarmingActivityRepository(session)
        for account in accounts:
            recent = wa_repo.list_by_account(account.id, limit=1)
            last_at = recent[0].created_at if recent else None
            interval = due_interval(account.warming_profile)
            if last_at is None or (now - last_at) >= interval:
                due.append(account.id)

    for account_id in due:
        await task_queue.enqueue(TaskName.WARMING_TICK, account_id)
    get_logger().info("warming.maintenance_scheduler.done", enqueued=due)
    return due


async def initial_start_impl(ctx: dict, account_id: int) -> int:
    """Стартер первичного прогрева: планирует стартовую пачку warming.tick.

    Вызывается сразу после перехода created → warming. Условие выхода в pool
    проверяется в каждом tick (см. :func:`_maybe_complete_warming`).
    """
    rng = _rng(ctx)
    task_queue = _task_queue(ctx)
    low, high = PRESET_ACTION_COUNT[INITIAL_BATCH_PROFILE]
    count = rng.randint(low, high)
    for _ in range(count):
        await task_queue.enqueue(TaskName.WARMING_TICK, account_id)
    get_logger().info("warming.initial_start", account_id=account_id, scheduled=count)
    return count
