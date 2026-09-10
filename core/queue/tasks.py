"""Тонкая обёртка над arq — транспорт задач, без бизнес-логики.

`TaskQueue` — единственная точка постановки задач в очередь. Бизнес-код зависит
от неё, а не от arq напрямую (PROJECT-STAGES §2). Имена задач валидируются по
:class:`TaskName` ещё до похода в Redis.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.constants import job_key_prefix

from core.config import get_settings
from core.queue.task_names import QueueName, TaskName

JobId = str

_pool: Optional[ArqRedis] = None
_pool_lock = asyncio.Lock()


async def get_task_pool() -> ArqRedis:
    """Пул arq/Redis, singleton на процесс (DSN из core.config)."""
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                settings = get_settings()
                _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _pool


async def close_task_pool() -> None:
    """Закрывает и сбрасывает singleton-пул (нужно в тестах/при остановке)."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


class TaskQueue:
    """Постановка задач в arq. Публичный API: enqueue / schedule / cancel."""

    def __init__(
        self,
        redis: Optional[ArqRedis] = None,
        queue: QueueName = QueueName.DEFAULT,
    ) -> None:
        self._redis = redis
        self._queue = queue

    async def enqueue(self, task_name: TaskName | str, *args: Any, **kwargs: Any) -> JobId:
        name = self._validate(task_name)
        pool = await self._pool()
        job = await pool.enqueue_job(name, *args, _queue_name=self._queue.value, **kwargs)
        if job is None:  # pragma: no cover - возможно только при явном _job_id
            raise RuntimeError(f"failed to enqueue task '{name}'")
        return job.job_id

    async def schedule(
        self, task_name: TaskName | str, run_at: datetime, *args: Any, **kwargs: Any
    ) -> JobId:
        name = self._validate(task_name)
        pool = await self._pool()
        job = await pool.enqueue_job(
            name, *args, _defer_until=run_at, _queue_name=self._queue.value, **kwargs
        )
        if job is None:  # pragma: no cover
            raise RuntimeError(f"failed to schedule task '{name}'")
        return job.job_id

    async def cancel(self, job_id: JobId) -> bool:
        pool = await self._pool()
        removed = await pool.zrem(self._queue.value, job_id)
        await pool.delete(job_key_prefix + job_id)
        return bool(removed)

    # ------------------------------------------------------------------ #
    async def _pool(self) -> ArqRedis:
        return self._redis if self._redis is not None else await get_task_pool()

    @staticmethod
    def _validate(task_name: TaskName | str) -> str:
        if isinstance(task_name, TaskName):
            return task_name.value
        try:
            return TaskName(task_name).value
        except ValueError:
            allowed = ", ".join(t.value for t in TaskName)
            raise ValueError(
                f"Unknown task name {task_name!r}. Allowed: {allowed}"
            ) from None
