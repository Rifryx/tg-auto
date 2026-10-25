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
    ChannelLifecycleListener,
    ChannelListenerRegistry,
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

    # Аккаунт-центричный мониторинг: слушатели working-каналов + их динамика
    # (channel_lifecycle: attach после resolve, detach при снятии с работы).
    channel_registry = ChannelListenerRegistry()
    ctx["channel_listener_registry"] = channel_registry
    await channel_registry.load_all(ctx)
    channel_lifecycle = ChannelLifecycleListener(
        channel_registry, ctx, settings.redis_url
    )
    ctx["channel_lifecycle"] = channel_lifecycle
    ctx["channel_lifecycle_task"] = asyncio.create_task(channel_lifecycle.run())

    # Live Interception шиллинга: подключаем слушателей ответов живого юзера
    # для всех running-кампаний с auto_responder != "off". Lifecycle через
    # Redis pub/sub (SHILLING_LIFECYCLE_CHANNEL): API-роуты start/stop
    # публикуют attach/detach, здесь слушаем и дёргаем реестр без рестарта.
    from modules.shilling.repositories import CampaignRepository as _ShRepo
    from modules.shilling.worker.live_interception import (
        LiveInterceptionRegistry,
        ShillingLifecycleListener,
    )

    shilling_live = LiveInterceptionRegistry()
    ctx["shilling_live_interception"] = shilling_live
    with ctx["session_factory"]() as _session:
        _running = [
            c
            for c in _ShRepo(_session).list_all()
            if c.enabled and c.status == "running" and c.auto_responder != "off"
        ]
    for _c in _running:
        try:
            await shilling_live.attach(ctx, _c)
        except Exception as _exc:  # noqa: BLE001 — не роняем старт воркера
            get_logger().warning(
                "shilling.live.startup_attach_failed",
                campaign_id=_c.id,
                error=repr(_exc),
            )

    shilling_lifecycle = ShillingLifecycleListener(shilling_live, ctx, settings.redis_url)
    ctx["shilling_live_lifecycle"] = shilling_lifecycle
    ctx["shilling_live_lifecycle_task"] = asyncio.create_task(shilling_lifecycle.run())

    get_logger().info(
        "worker.startup",
        functions=[f.name for f in TASK_FUNCTIONS],
        cron_jobs=[c.name for c in CRON_JOBS],
        registered=registered_names(),
        listeners=registry.active(),
        channel_listeners=channel_registry.active(),
        shilling_live_handlers=shilling_live.active_handlers(),
    )


async def shutdown(ctx: dict) -> None:
    for task_key in (
        "campaign_lifecycle_task",
        "channel_lifecycle_task",
        "shilling_live_lifecycle_task",
    ):
        task = ctx.get(task_key)
        if task is not None:
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
    for lc_key in (
        "campaign_lifecycle",
        "channel_lifecycle",
        "shilling_live_lifecycle",
    ):
        lifecycle = ctx.get(lc_key)
        if lifecycle is not None:
            await lifecycle.stop()
    for reg_key in ("listener_registry", "channel_listener_registry"):
        registry = ctx.get(reg_key)
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
