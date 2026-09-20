"""Тела bulk-задач (этап 5 УТП).

* ``bulk.dispatch`` — читает pending-item'ы job'а и ставит ``bulk.item`` для
  каждого. Job переводится в ``running``. Идемпотентно: если item уже
  ``done``/``running``/``failed`` — не ставим повторно.
* ``bulk.item`` — выполняет один action над одним аккаунтом:
  1) проверяет статус аккаунта (banned/retired → skipped);
  2) если у action указан ``governor_key`` — резервирует слот через governor;
     при отказе item остаётся ``pending``, задача заново шедулится с backoff.
  3) для действий с ``requires_client=True`` берёт клиент из ``ClientPool``;
  4) вызывает ``action.run(...)`` в try/finally для release клиента;
  5) обновляет item и job-счётчики;
  6) публикует ``bulk.progress``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from core.enums import AccountStatus, BulkItemStatus
from core.queue import TaskQueue
from core.queue.publisher import Publisher
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from core.repositories.bulk_job import BulkJobRepository
from modules.bulk.actions import ACTION_REGISTRY
from worker.tasks.logging import get_logger

BULK_PROGRESS_CHANNEL = "bulk.progress"

# Задержка перед повторной постановкой rate-limited item'а (этап 5, backlog #1).
# Часовое окно governor'а — берём 5 минут, чтобы к следующему тику окно уже
# успело сдвинуться (реже — упрёмся в тот же лимит; чаще — заспамим Redis).
_GOVERNOR_BACKOFF_SECONDS = 5 * 60

_UNAVAILABLE_STATUSES = frozenset(
    {AccountStatus.BANNED.value, AccountStatus.RETIRED.value}
)


async def dispatch_impl(ctx: dict, job_id: int) -> dict[str, Any]:
    """Ставит ``bulk.item`` для каждого pending-item'а."""
    session_factory = ctx["session_factory"]
    queue = TaskQueue(redis=ctx.get("redis"))
    now = ctx.get("now") or datetime.now(timezone.utc)

    with session_factory() as session:
        repo = BulkJobRepository(session)
        job = repo.get(job_id)
        if job is None:
            get_logger().warning("bulk.dispatch.missing_job", job_id=job_id)
            return {"enqueued": 0, "reason": "missing_job"}
        if job.action_type not in ACTION_REGISTRY:
            get_logger().error(
                "bulk.dispatch.unknown_action",
                job_id=job_id,
                action_type=job.action_type,
            )
            return {"enqueued": 0, "reason": "unknown_action"}
        pending = repo.list_pending_items(job_id)
        repo.mark_running(job_id, now=now)
        session.commit()
        item_ids = [it.id for it in pending]

    for item_id in item_ids:
        await queue.enqueue(TaskName.BULK_ITEM, job_id, item_id)

    get_logger().info("bulk.dispatch.done", job_id=job_id, enqueued=len(item_ids))
    return {"enqueued": len(item_ids)}


async def item_impl(ctx: dict, job_id: int, item_id: int) -> dict[str, Any]:
    """Выполняет одну операцию из bulk-задания."""
    session_factory = ctx["session_factory"]
    publisher: Optional[Publisher] = ctx.get("publisher")
    client_pool = ctx.get("client_pool")
    now = ctx.get("now") or datetime.now(timezone.utc)

    # 1) Читаем состояние item/job.
    with session_factory() as session:
        repo = BulkJobRepository(session)
        item = repo.get_item(item_id)
        job = repo.get(job_id)
        if item is None or job is None:
            return {"skipped": True, "reason": "missing"}
        if item.status != BulkItemStatus.PENDING.value:
            return {"skipped": True, "reason": f"already:{item.status}"}
        action = ACTION_REGISTRY.get(job.action_type)
        if action is None:
            repo.apply_item_result(
                item_id,
                status=BulkItemStatus.FAILED,
                error=f"unknown_action:{job.action_type}",
                started_at=now,
                finished_at=now,
            )
            repo.recompute_counters(job_id)
            session.commit()
            _publish(publisher, job_id, item_id, BulkItemStatus.FAILED)
            return {"failed": True, "reason": "unknown_action"}

        # Проверка доступности аккаунта.
        account = AccountRepository(session).get(item.account_id)
        if account is None or account.status in _UNAVAILABLE_STATUSES:
            repo.apply_item_result(
                item_id,
                status=BulkItemStatus.SKIPPED,
                error=None if account is not None else "account_missing",
                result={"account_status": account.status if account else None},
                started_at=now,
                finished_at=now,
            )
            repo.recompute_counters(job_id)
            session.commit()
            _publish(publisher, job_id, item_id, BulkItemStatus.SKIPPED)
            return {"skipped": True, "reason": "account_unavailable"}

        # Помечаем RUNNING (отдельным commit'ом, чтобы UI видел прогресс).
        repo.apply_item_result(
            item_id, status=BulkItemStatus.RUNNING, started_at=now
        )
        session.commit()
        payload_raw = job.payload
        account_id = item.account_id
        action_name = job.action_type

    # 2) Валидируем payload вне сессии — pydantic-модель, ошибка → item failed.
    try:
        payload = action.payload_schema.model_validate(payload_raw)
    except Exception as exc:  # noqa: BLE001
        _finalize_failed(session_factory, publisher, job_id, item_id, repr(exc), now)
        return {"failed": True, "reason": "invalid_payload"}

    # 2b) Governor (этап 5, backlog #1): для действий с указанным governor_key
    # резервируем слот. Если лимит исчерпан — item возвращается в pending и
    # шедулится через ~5 минут, счётчики job не двигаем. В runtime без Redis
    # governor всё равно fail-open, так что локальные тесты не блокируются.
    if action.governor_key is not None:
        governor = ctx.get("governor")
        if governor is None:
            # Ленивая сборка поверх arq ctx['redis'] — тот же паттерн, что в
            # worker/login/flow.py::_governor и worker/tasks/warming.py.
            from worker.health import Governor as _Governor
            governor = _Governor(ctx.get("redis"))
        allowed = await governor.check_and_reserve(account_id, action.governor_key)
        if not allowed:
            await _reschedule_rate_limited(
                session_factory, publisher, ctx,
                job_id=job_id, item_id=item_id, now=now,
            )
            get_logger().info(
                "bulk.item.rate_limited",
                job_id=job_id, item_id=item_id, action=action_name,
                governor_key=action.governor_key,
            )
            return {"skipped": True, "reason": "rate_limited"}

    # 3) Выполняем действие.
    client = None
    try:
        if action.requires_client:
            if client_pool is None:
                raise RuntimeError("client_pool not available in worker ctx")
            client = await client_pool.get(account_id)
        result = await action.run(
            account_id=account_id,
            payload=payload,
            session_factory=session_factory,
            publisher=publisher,
            client=client,
        )
    except Exception as exc:  # noqa: BLE001 — фиксируем как failed
        _finalize_failed(session_factory, publisher, job_id, item_id, repr(exc), now)
        get_logger().warning(
            "bulk.item.failed",
            job_id=job_id, item_id=item_id, action=action_name, error=repr(exc),
        )
        return {"failed": True, "reason": "exception"}
    finally:
        if client is not None and client_pool is not None:
            await client_pool.release(account_id)

    finished_at = datetime.now(timezone.utc)
    status = (
        BulkItemStatus.SKIPPED if result.skipped
        else BulkItemStatus.DONE if result.ok
        else BulkItemStatus.FAILED
    )
    with session_factory() as session:
        repo = BulkJobRepository(session)
        repo.apply_item_result(
            item_id,
            status=status,
            result=result.detail,
            error=None if result.ok else "action_returned_not_ok",
            finished_at=finished_at,
        )
        repo.recompute_counters(job_id)
        session.commit()
    _publish(publisher, job_id, item_id, status)
    return {"status": status.value, "detail": result.detail}


async def _reschedule_rate_limited(
    session_factory,
    publisher: Optional[Publisher],
    ctx: dict,
    *,
    job_id: int,
    item_id: int,
    now: datetime,
) -> None:
    """Rate-limit path (этап 5, backlog #1): item возвращается в pending,
    задача шедулится через backoff. Счётчики job'а не двигаем — item как
    будто не начинали (see recompute_counters ниже, но mark PENDING).
    """
    with session_factory() as session:
        repo = BulkJobRepository(session)
        # Возвращаем в PENDING, чистим started_at (item был помечен RUNNING
        # выше в item_impl → apply_item_result не примет None для сброса,
        # поэтому обнуляем поле напрямую после смены статуса).
        item = repo.apply_item_result(
            item_id,
            status=BulkItemStatus.PENDING,
            error=None,
        )
        if item is not None:
            item.started_at = None
            item.finished_at = None
        repo.recompute_counters(job_id)
        session.commit()

    # В тестах ctx["task_queue"] — spy; в проде на arq — используем реальную
    # TaskQueue поверх ctx["redis"].
    queue = ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))
    run_at = now + timedelta(seconds=_GOVERNOR_BACKOFF_SECONDS)
    await queue.schedule(TaskName.BULK_ITEM, run_at, job_id, item_id)

    if publisher is not None:
        publisher.publish(
            BULK_PROGRESS_CHANNEL,
            {
                "job_id": job_id,
                "item_id": item_id,
                "status": BulkItemStatus.PENDING.value,
                "reason": "rate_limited",
            },
        )


def _finalize_failed(
    session_factory, publisher: Optional[Publisher],
    job_id: int, item_id: int, error: str, now: datetime,
) -> None:
    with session_factory() as session:
        repo = BulkJobRepository(session)
        repo.apply_item_result(
            item_id,
            status=BulkItemStatus.FAILED,
            error=error,
            finished_at=now,
        )
        repo.recompute_counters(job_id)
        session.commit()
    _publish(publisher, job_id, item_id, BulkItemStatus.FAILED)


def _publish(
    publisher: Optional[Publisher], job_id: int, item_id: int, status: BulkItemStatus
) -> None:
    if publisher is None:
        return
    publisher.publish(
        BULK_PROGRESS_CHANNEL,
        {"job_id": job_id, "item_id": item_id, "status": status.value},
    )
