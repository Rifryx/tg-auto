"""Bootstrap воркер-процесса arq.

Запуск: ``arq worker.main.WorkerSettings``. Регистрирует все задачи (§2/§4),
настраивает structlog-логирование и кладёт в контекст фабрику сессий БД и
pub/sub-паблишер. Бизнес-логики задач здесь нет.
"""

from __future__ import annotations

from arq.connections import RedisSettings

from core.config import get_settings
from core.queue.publisher import RedisPublisher
from core.queue.task_names import QueueName
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
    ctx["publisher"] = RedisPublisher(ctx["redis"])
    get_logger().info(
        "worker.startup",
        functions=[f.name for f in TASK_FUNCTIONS],
        cron_jobs=[c.name for c in CRON_JOBS],
        registered=registered_names(),
    )


async def shutdown(ctx: dict) -> None:
    get_logger().info("worker.shutdown")


class WorkerSettings:
    functions = TASK_FUNCTIONS
    cron_jobs = CRON_JOBS
    on_startup = startup
    on_shutdown = shutdown
    queue_name = QueueName.DEFAULT.value
    max_tries = 3
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
