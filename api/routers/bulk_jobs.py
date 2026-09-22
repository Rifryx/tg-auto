"""API bulk-заданий (этап 5 УТП).

Пользователь выбирает выборку аккаунтов, тип действия и общий payload; API:
1) валидирует action_type и payload через ``modules.bulk.actions.ACTION_REGISTRY``;
2) валидирует существование всех account_id;
3) создаёт ``bulk_jobs`` + ``bulk_job_items`` в БД;
4) ставит ``bulk.dispatch`` в очередь.

Прогресс и итоги читаются через ``GET /bulk-jobs/{id}``. Live-обновления —
через SSE ``/monitoring/stream`` (канал ``bulk.progress``).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from core.models import BulkJob
from core.queue import TaskQueue
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from core.repositories.bulk_job import BulkJobRepository
from core.schemas.bulk import (
    BulkJobCreate,
    BulkJobDetail,
    BulkJobItemRead,
    BulkJobRead,
)
from modules.bulk.actions import ACTION_REGISTRY

router = APIRouter(
    prefix="/bulk-jobs", tags=["bulk-jobs"], dependencies=[Depends(require_user)]
)


def _get_or_404(session: Session, job_id: int) -> BulkJob:
    job = BulkJobRepository(session).get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"bulk job {job_id} not found")
    return job


@router.get("/actions")
def list_bulk_actions() -> list[dict]:
    """Каталог bulk-действий с JSON-schema payload'а (этап 5, backlog #2).

    Mini-app по этому каталогу рендерит форму: title/description — метаданные,
    ``payload_schema`` — pydantic JSON-schema для генерации полей ввода;
    ``requires_client`` — подсказка UI, что при выборке аккаунтов надо
    исключать retired/banned. Порядок стабилен по ключу name.
    """
    items = []
    for name in sorted(ACTION_REGISTRY.keys()):
        action = ACTION_REGISTRY[name]
        items.append(
            {
                "name": name,
                "title": action.title,
                "description": action.description,
                "requires_client": action.requires_client,
                "governor_key": action.governor_key,
                "payload_schema": action.payload_schema.model_json_schema(),
            }
        )
    return items


@router.post("", response_model=BulkJobRead, status_code=status.HTTP_201_CREATED)
async def create_bulk_job(
    body: BulkJobCreate,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
) -> BulkJobRead:
    action = ACTION_REGISTRY.get(body.action_type.value)
    if action is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown bulk action: {body.action_type.value}",
        )

    # Валидация payload'а по схеме конкретного action'а.
    try:
        action.payload_schema.model_validate(body.payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"invalid payload for {body.action_type.value}: {exc}",
        ) from exc

    if not body.account_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "account_ids is empty"
        )
    repo_accounts = AccountRepository(session)
    missing = [aid for aid in body.account_ids if repo_accounts.get(aid) is None]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown account ids: {missing}",
        )

    repo = BulkJobRepository(session)
    job = repo.create(
        action_type=body.action_type.value,
        payload=body.payload,
        initiator=user_id,
        account_ids=body.account_ids,
    )
    session.commit()

    await task_queue.enqueue(TaskName.BULK_DISPATCH, job.id)
    return BulkJobRead.model_validate(job)


@router.get("", response_model=list[BulkJobRead])
def list_bulk_jobs(
    initiator: Optional[str] = None,
    session: Session = Depends(get_session),
) -> list[BulkJobRead]:
    stmt = select(BulkJob).order_by(BulkJob.created_at.desc())
    if initiator is not None:
        stmt = stmt.where(BulkJob.initiator == initiator)
    return [BulkJobRead.model_validate(j) for j in session.execute(stmt).scalars().all()]


@router.get("/{job_id}", response_model=BulkJobDetail)
def get_bulk_job(job_id: int, session: Session = Depends(get_session)) -> BulkJobDetail:
    job = _get_or_404(session, job_id)
    items = BulkJobRepository(session).list_items(job_id)
    return BulkJobDetail(
        job=BulkJobRead.model_validate(job),
        items=[BulkJobItemRead.model_validate(i) for i in items],
    )


@router.post("/{job_id}/cancel", response_model=BulkJobRead)
def cancel_bulk_job(
    job_id: int, session: Session = Depends(get_session)
) -> BulkJobRead:
    job = BulkJobRepository(session).cancel(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"bulk job {job_id} not found")
    session.commit()
    return BulkJobRead.model_validate(job)


@router.post("/{job_id}/retry-failed", response_model=BulkJobRead)
async def retry_failed(
    job_id: int,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
) -> BulkJobRead:
    repo = BulkJobRepository(session)
    job = _get_or_404(session, job_id)
    reset = repo.reset_failed_to_pending(job_id)
    session.commit()
    if reset == 0:
        return BulkJobRead.model_validate(job)
    await task_queue.enqueue(TaskName.BULK_DISPATCH, job_id)
    return BulkJobRead.model_validate(repo.get(job_id))
