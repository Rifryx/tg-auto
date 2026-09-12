"""Регистрация всех задач воркера (PROJECT-STAGES §2/§4).

Все задачи из полного списка зарегистрированы явно. Тело каждой — заглушка
(логирует получение и бросает NotImplementedError), КРОМЕ:
- ``health.cooldown_return`` — реальная work-функция (возврат из cooldown);
- ``warming.maintenance_scheduler`` — заглушка, но зарегистрирована как cron
  (каждые 5 минут), тело только логирует и возвращает управление.

Здесь только диспетчеризация: никакого Telethon/LLM/HTTP.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from arq import cron
from arq.worker import func

from core.enums import Initiator
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from core.state_machine import AccountEvent, AccountStateMachine
from worker.login import (
    login_confirm_impl,
    login_password_impl,
    login_start_impl,
)
from worker.tasks.dispatch import task
from worker.tasks.logging import get_logger
from worker.tasks.warming import maintenance_scheduler_impl, warming_tick_impl

# Задачи, которые пока заглушки (реальная реализация — на своих этапах).
_STUB_TASKS = [
    TaskName.ACCOUNT_START_WARMING,
    TaskName.HEALTH_CHECK_PROXIES,
    TaskName.ACCOUNT_RETIRE,
    TaskName.ACCOUNT_ACKNOWLEDGE_BAN,
    TaskName.COMMENTING_ON_NEW_POST,
    TaskName.COMMENTING_POST_COMMENT,
]


def _make_stub(name: str):
    async def stub(ctx: dict, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(f"task '{name}' is not implemented yet")

    stub.__name__ = name.replace(".", "_")
    return stub


async def cooldown_return_impl(ctx: dict, *args: Any, **kwargs: Any) -> list[int]:
    """Возвращает аккаунты с истёкшим cooldown в previous_status через SM."""
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    now = datetime.now(timezone.utc)
    returned: list[int] = []
    with session_factory() as session:
        repo = AccountRepository(session)
        machine = AccountStateMachine(session, publisher)
        for account in repo.list_cooldown_expired(now):
            machine.transition(account.id, AccountEvent.COOLDOWN_EXPIRED, Initiator.AUTO)
            returned.append(account.id)
    get_logger().info("cooldown_return.done", count=len(returned), account_ids=returned)
    return returned


# Декорированные и зарегистрированные задачи.
cooldown_return = task(TaskName.HEALTH_COOLDOWN_RETURN.value)(cooldown_return_impl)

# Прогрев (§3): тела в worker/tasks/warming.py и worker/warming.
maintenance_scheduler = task(TaskName.WARMING_MAINTENANCE_SCHEDULER.value)(
    maintenance_scheduler_impl
)
warming_tick = task(TaskName.WARMING_TICK.value)(warming_tick_impl)

# Логин-флоу (§3.2/§11): тела в worker/login, здесь только регистрация.
login_start = task(TaskName.ACCOUNT_LOGIN_START.value)(login_start_impl)
login_confirm = task(TaskName.ACCOUNT_LOGIN_CONFIRM.value)(login_confirm_impl)
login_password = task(TaskName.ACCOUNT_LOGIN_PASSWORD.value)(login_password_impl)

TASK_FUNCTIONS = [
    func(task(name.value)(_make_stub(name.value)), name=name.value, max_tries=3)
    for name in _STUB_TASKS
] + [
    func(warming_tick, name=TaskName.WARMING_TICK.value, max_tries=3),
    func(login_start, name=TaskName.ACCOUNT_LOGIN_START.value, max_tries=3),
    func(login_confirm, name=TaskName.ACCOUNT_LOGIN_CONFIRM.value, max_tries=3),
    func(login_password, name=TaskName.ACCOUNT_LOGIN_PASSWORD.value, max_tries=3),
    # cooldown_return: max_tries=1 — при сбое повторится по крону
    func(cooldown_return, name=TaskName.HEALTH_COOLDOWN_RETURN.value, max_tries=1),
]

CRON_JOBS = [
    cron(
        maintenance_scheduler,
        name=TaskName.WARMING_MAINTENANCE_SCHEDULER.value,
        minute=set(range(0, 60, 5)),
        run_at_startup=False,
        max_tries=1,
    ),
]


def registered_names() -> list[str]:
    """Имена всех зарегистрированных задач (функции + cron)."""
    return [f.name for f in TASK_FUNCTIONS] + [c.name for c in CRON_JOBS]
