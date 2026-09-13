"""Bootstrap воркер-процесса arq.

Запуск: ``arq worker.main.WorkerSettings``. Регистрирует все задачи (§2/§4),
настраивает structlog-логирование и кладёт в контекст фабрику сессий БД и
pub/sub-паблишер. Бизнес-логики задач здесь нет.
"""

from __future__ import annotations

import asyncio

from arq.connections import RedisSettings

from core.config import get_settings
from core.queue.publisher import build_redis_publisher
from core.queue.task_names import QueueName
from modules.commenting.worker.registry import (
    CampaignLifecycleListener,
    ListenerRegistry,
)
from worker.client_pool import ClientPool
from worker.tasks import (
    CRON_JOBS,
    TASK_FUNCTIONS,
    build_session_factory,
    configure_logging,
    get_logger,
    registered_names,
)

configure_logging()


async def startup(ctx: dict) -> None:
    settings = get_settings()
    ctx["session_factory"] = build_session_factory(settings.database_url)
    # Синхронный публикатор (не arq-редис ctx['redis'], который async — иначе
    # publish возвращал бы неожиданную корутину и событие не уходило).
    ctx["publisher"] = build_redis_publisher(settings.redis_url)

    # ClientPool кладём в ctx СРАЗУ и явно (не лениво): от него зависят и
    # слушатели кампаний, и login/warming/commenting-задачи (аудит #12).
    ctx["client_pool"] = ClientPool(ctx["session_factory"])

    # Слушатели кампаний подключаем ПОСЛЕ готового client_pool (аудит #4).
    registry = ListenerRegistry()
    ctx["listener_registry"] = registry
    await registry.load_all(ctx)

    # Динамика без рестарта: фоновая задача слушает campaign_lifecycle весь
    # срок жизни воркера (attach/detach по событиям API).
    lifecycle = CampaignLifecycleListener(registry, ctx, settings.redis_url)
    ctx["campaign_lifecycle"] = lifecycle
    ctx["campaign_lifecycle_task"] = asyncio.create_task(lifecycle.run())

    get_logger().info(
        "worker.startup",
        functions=[f.name for f in TASK_FUNCTIONS],
        cron_jobs=[c.name for c in CRON_JOBS],
        registered=registered_names(),
        listeners=registry.active(),
    )


async def shutdown(ctx: dict) -> None:
    task = ctx.get("campaign_lifecycle_task")
    if task is not None:
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
    lifecycle = ctx.get("campaign_lifecycle")
    if lifecycle is not None:
        await lifecycle.stop()
    registry = ctx.get("listener_registry")
    if registry is not None:
        await registry.close_all()
    pool = ctx.get("client_pool")
    if pool is not None:
        await pool.close_all()
    get_logger().info("worker.shutdown")


class WorkerSettings:
    functions = TASK_FUNCTIONS
    cron_jobs = CRON_JOBS
    on_startup = startup
    on_shutdown = shutdown
    queue_name = QueueName.DEFAULT.value
    max_tries = 3
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
