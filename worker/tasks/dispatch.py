"""Диспетчер задач воркера: логирование, ретраи, обработка FloodWait.

Оборачивает каждую задачу. Ответственности (и только они — бизнес-логики нет):
- structlog-логи старта/финиша/ошибки со временем выполнения;
- FloodWaitError -> перепланирование той же задачи на ``now + wait_seconds``
  через :class:`TaskQueue`, без пометки провала;
- любое другое исключение -> ``arq.Retry`` (arq повторит до ``max_tries``, затем
  сам пометит задачу failed — обычные исключения arq иначе не ретраит).
"""

from __future__ import annotations

import functools
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from arq import Retry

from core.queue import TaskQueue
from worker.tasks.logging import get_logger

TaskCoroutine = Callable[..., Awaitable[Any]]


class FloodWaitError(Exception):
    """Локальный аналог Telethon FloodWait: несёт ``seconds`` до повтора.

    Собственный тип, чтобы диспетчер не зависел от Telethon (в воркере-диспетчере
    работы с Telethon нет).
    """

    def __init__(self, seconds: int) -> None:
        super().__init__(f"flood wait: retry after {seconds}s")
        self.seconds = seconds


def task(name: str) -> Callable[[TaskCoroutine], TaskCoroutine]:
    """Оборачивает корутину задачи диспетчерской логикой. ``name`` — имя задачи."""

    def decorator(coro: TaskCoroutine) -> TaskCoroutine:
        @functools.wraps(coro)
        async def wrapper(ctx: dict, *args: Any, **kwargs: Any) -> Any:
            log = get_logger().bind(
                task=name, job_id=ctx.get("job_id"), job_try=ctx.get("job_try")
            )
            started = time.perf_counter()
            log.info("task.start")
            try:
                result = await coro(ctx, *args, **kwargs)
            except FloodWaitError as exc:
                run_at = datetime.now(timezone.utc) + timedelta(seconds=exc.seconds)
                await TaskQueue(redis=ctx.get("redis")).schedule(name, run_at, *args, **kwargs)
                log.warning(
                    "task.flood_wait",
                    wait_seconds=exc.seconds,
                    reschedule_at=run_at.isoformat(),
                    duration=round(time.perf_counter() - started, 4),
                )
                return None
            except Exception as exc:
                log.error(
                    "task.failed",
                    error=repr(exc),
                    duration=round(time.perf_counter() - started, 4),
                    exc_info=True,
                )
                # arq не ретраит обычные исключения сам — просим повтор явно.
                raise Retry(defer=0) from exc
            log.info("task.finish", duration=round(time.perf_counter() - started, 4))
            return result

        return wrapper

    return decorator
