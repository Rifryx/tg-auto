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
from worker.tasks.commenting import (
    leave_channel_impl,
    on_channel_post_impl,
    on_new_post_impl,
    post_channel_comment_impl,
    post_comment_impl,
    resolve_channel_impl,
    backfill_channel_impl,
    sync_account_subscriptions_impl,
    verify_comment_impl,
    sync_campaign_channels_impl,
)
from worker.tasks.bulk import dispatch_impl as bulk_dispatch_impl, item_impl as bulk_item_impl
from worker.tasks.dispatch import task
from worker.tasks.health import (
    check_account_impl,
    check_accounts_periodic_impl,
    check_proxies_impl,
    recompute_score_impl,
)
from worker.tasks.autopilot import autopilot_tick_impl
from worker.tasks.predictor import (
    predict_ban_risk_batch_impl,
    predict_ban_risk_impl,
)
from worker.tasks.security import (
    confirm_recovery_email_impl,
    request_recovery_email_impl,
)
from worker.tasks.logging import get_logger
from worker.tasks.warming import (
    initial_start_impl,
    maintenance_scheduler_impl,
    warming_tick_impl,
)

# Задачи, которые пока заглушки (реальная реализация — на своих этапах).
_STUB_TASKS = [
    TaskName.ACCOUNT_RETIRE,
    TaskName.ACCOUNT_ACKNOWLEDGE_BAN,
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
# Стартер первичного прогрева: enqueue'ится напрямую из login/flow.py::_finish_login
# сразу после перехода created → warming (промежуточная задача-обёртка удалена
# как лишний слой индирекции — прямой enqueue надёжнее).
warming_initial_start = task(TaskName.WARMING_INITIAL_START.value)(initial_start_impl)

# Health (§5.3): проверка прокси — cron каждые 10 минут.
check_proxies = task(TaskName.HEALTH_CHECK_PROXIES.value)(check_proxies_impl)
# Health (§5.3, этап 4): активные пробы аккаунтов + периодический планировщик.
check_account = task(TaskName.HEALTH_CHECK_ACCOUNT.value)(check_account_impl)
check_accounts_periodic = task(TaskName.HEALTH_CHECK_ACCOUNTS_PERIODIC.value)(
    check_accounts_periodic_impl
)
recompute_score = task(TaskName.HEALTH_RECOMPUTE_SCORE.value)(recompute_score_impl)

# Anti-Ban Predictor (этап 11).
predict_ban_risk = task(TaskName.HEALTH_PREDICT_BAN_RISK.value)(predict_ban_risk_impl)
predict_ban_risk_batch = task(TaskName.HEALTH_PREDICT_BAN_RISK_BATCH.value)(
    predict_ban_risk_batch_impl
)

# Autopilot (этап 12): cron-планировщик действий над парком.
autopilot_tick = task(TaskName.AUTOPILOT_TICK.value)(autopilot_tick_impl)

# Security recovery-email flow (этап 7, backlog #1).
request_recovery_email = task(TaskName.SECURITY_REQUEST_RECOVERY_EMAIL.value)(
    request_recovery_email_impl
)
confirm_recovery_email = task(TaskName.SECURITY_CONFIRM_RECOVERY_EMAIL.value)(
    confirm_recovery_email_impl
)

# Bulk-операции (§5.5 — этап 5 УТП). dispatch распределяет по item'ам, item —
# сам исполнитель одного действия для одного аккаунта.
bulk_dispatch = task(TaskName.BULK_DISPATCH.value)(bulk_dispatch_impl)
bulk_item = task(TaskName.BULK_ITEM.value)(bulk_item_impl)

# Модуль commenting (§5): тела в modules/commenting/worker/runner.
on_new_post = task(TaskName.COMMENTING_ON_NEW_POST.value)(on_new_post_impl)
post_comment = task(TaskName.COMMENTING_POST_COMMENT.value)(post_comment_impl)
# Аккаунт-центричный мониторинг каналов (тела в .../channels и .../runner).
resolve_channel = task(TaskName.COMMENTING_RESOLVE_CHANNEL.value)(resolve_channel_impl)
leave_channel = task(TaskName.COMMENTING_LEAVE_CHANNEL.value)(leave_channel_impl)
sync_campaign_channels = task(TaskName.COMMENTING_SYNC_CAMPAIGN_CHANNELS.value)(
    sync_campaign_channels_impl
)
sync_account_subscriptions = task(TaskName.COMMENTING_SYNC_ACCOUNT_SUBSCRIPTIONS.value)(
    sync_account_subscriptions_impl
)
backfill_channel = task(TaskName.COMMENTING_BACKFILL_CHANNEL.value)(backfill_channel_impl)
verify_comment = task(TaskName.COMMENTING_VERIFY_COMMENT.value)(verify_comment_impl)
on_channel_post = task(TaskName.COMMENTING_ON_CHANNEL_POST.value)(on_channel_post_impl)
post_channel_comment = task(TaskName.COMMENTING_POST_CHANNEL_COMMENT.value)(
    post_channel_comment_impl
)

# Логин-флоу (§3.2/§11): тела в worker/login, здесь только регистрация.
login_start = task(TaskName.ACCOUNT_LOGIN_START.value)(login_start_impl)
login_confirm = task(TaskName.ACCOUNT_LOGIN_CONFIRM.value)(login_confirm_impl)
login_password = task(TaskName.ACCOUNT_LOGIN_PASSWORD.value)(login_password_impl)

TASK_FUNCTIONS = [
    func(task(name.value)(_make_stub(name.value)), name=name.value, max_tries=3)
    for name in _STUB_TASKS
] + [
    func(warming_tick, name=TaskName.WARMING_TICK.value, max_tries=3),
    func(
        warming_initial_start,
        name=TaskName.WARMING_INITIAL_START.value,
        max_tries=3,
    ),
    func(on_new_post, name=TaskName.COMMENTING_ON_NEW_POST.value, max_tries=3),
    func(post_comment, name=TaskName.COMMENTING_POST_COMMENT.value, max_tries=3),
    func(resolve_channel, name=TaskName.COMMENTING_RESOLVE_CHANNEL.value, max_tries=3),
    func(leave_channel, name=TaskName.COMMENTING_LEAVE_CHANNEL.value, max_tries=2),
    func(
        sync_campaign_channels,
        name=TaskName.COMMENTING_SYNC_CAMPAIGN_CHANNELS.value,
        max_tries=3,
    ),
    # Разбор подписок ходит в Telegram — без агрессивных ретраев.
    func(
        sync_account_subscriptions,
        name=TaskName.COMMENTING_SYNC_ACCOUNT_SUBSCRIPTIONS.value,
        max_tries=2,
    ),
    # Backfill истории канала: батчами с паузами, повтор мог бы задвоить
    # запланированные комментарии — max_tries=1.
    func(
        backfill_channel,
        name=TaskName.COMMENTING_BACKFILL_CHANNEL.value,
        max_tries=1,
    ),
    # Verify-after-post: пропускаем при ошибке (не «удалено»), max_tries=2.
    func(
        verify_comment,
        name=TaskName.COMMENTING_VERIFY_COMMENT.value,
        max_tries=2,
    ),
    func(on_channel_post, name=TaskName.COMMENTING_ON_CHANNEL_POST.value, max_tries=3),
    func(
        post_channel_comment,
        name=TaskName.COMMENTING_POST_CHANNEL_COMMENT.value,
        max_tries=3,
    ),
    func(login_start, name=TaskName.ACCOUNT_LOGIN_START.value, max_tries=3),
    func(login_confirm, name=TaskName.ACCOUNT_LOGIN_CONFIRM.value, max_tries=3),
    func(login_password, name=TaskName.ACCOUNT_LOGIN_PASSWORD.value, max_tries=3),
    # Recovery-email flow (этап 7, backlog #1): max_tries=1 — при
    # EmailUnconfirmedError мы уже сохранили pending, повторный вызов только
    # спутает Telegram.
    func(
        request_recovery_email,
        name=TaskName.SECURITY_REQUEST_RECOVERY_EMAIL.value,
        max_tries=1,
    ),
    func(
        confirm_recovery_email,
        name=TaskName.SECURITY_CONFIRM_RECOVERY_EMAIL.value,
        max_tries=1,
    ),
    # cooldown_return: max_tries=1 — при сбое повторится по крону
    func(cooldown_return, name=TaskName.HEALTH_COOLDOWN_RETURN.value, max_tries=1),
    func(check_account, name=TaskName.HEALTH_CHECK_ACCOUNT.value, max_tries=2),
    func(recompute_score, name=TaskName.HEALTH_RECOMPUTE_SCORE.value, max_tries=2),
    func(bulk_dispatch, name=TaskName.BULK_DISPATCH.value, max_tries=2),
    # bulk.item: 1 попытка. Failed item'ы возвращаются пользователем через
    # retry-failed endpoint — иначе повторы прячут проблемы (напр., мёртвая
    # сессия) под max_tries.
    func(bulk_item, name=TaskName.BULK_ITEM.value, max_tries=1),
    func(predict_ban_risk, name=TaskName.HEALTH_PREDICT_BAN_RISK.value, max_tries=2),
]

CRON_JOBS = [
    cron(
        maintenance_scheduler,
        name=TaskName.WARMING_MAINTENANCE_SCHEDULER.value,
        minute=set(range(0, 60, 5)),
        run_at_startup=False,
        max_tries=1,
    ),
    cron(
        check_proxies,
        name=TaskName.HEALTH_CHECK_PROXIES.value,
        minute=set(range(0, 60, 10)),
        run_at_startup=False,
        max_tries=1,
    ),
    # health.check_accounts_periodic: раз в 3 часа шедулит check_account для
    # аккаунтов, у которых пришло время (адаптивно: 3ч для at-risk, 12ч базово).
    cron(
        check_accounts_periodic,
        name=TaskName.HEALTH_CHECK_ACCOUNTS_PERIODIC.value,
        hour=set(range(0, 24, 3)),
        minute={5},
        run_at_startup=False,
        max_tries=1,
    ),
    # Anti-Ban Predictor batch: раз в 15 минут обновляет риск для всех активных.
    cron(
        predict_ban_risk_batch,
        name=TaskName.HEALTH_PREDICT_BAN_RISK_BATCH.value,
        minute=set(range(0, 60, 15)),
        run_at_startup=False,
        max_tries=1,
    ),
    # Autopilot: раз в 10 минут пересматривает цели и раздаёт задания.
    cron(
        autopilot_tick,
        name=TaskName.AUTOPILOT_TICK.value,
        minute=set(range(0, 60, 10)),
        run_at_startup=False,
        max_tries=1,
    ),
]


def registered_names() -> list[str]:
    """Имена всех зарегистрированных задач (функции + cron)."""
    return [f.name for f in TASK_FUNCTIONS] + [c.name for c in CRON_JOBS]
