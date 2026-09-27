"""Роутер модуля парсинга (промпт 3.2b).

Префикс ``/modules/parsing``. CRUD-читатель для списков + endpoint
запуска парсера. Сам парсер (Telethon-heavy) вызывается из worker'а
через arq-задачу; здесь только создание list-заготовки и enqueue.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from core.queue import TaskQueue
from core.queue.task_names import TaskName
from modules.parsing.repositories import (
    ParsedListRepository,
    ParsedListTargetRepository,
)
from modules.parsing.schemas import (
    ParsedListRead,
    ParsedListTargetRead,
    RunChatMembersRequest,
    RunChatMessagesRequest,
)


router = APIRouter(
    prefix="/modules/parsing",
    tags=["parsing"],
    dependencies=[Depends(require_user)],
)


def _owner_id(user_id: str) -> int:
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return 0


@router.get("/lists", response_model=list[ParsedListRead])
def list_lists(
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
):
    return [
        ParsedListRead.model_validate(r)
        for r in ParsedListRepository(session).list_by_owner(_owner_id(user_id))
    ]


@router.get("/lists/{list_id}", response_model=ParsedListRead)
def get_list(list_id: int, session: Session = Depends(get_session)):
    obj = ParsedListRepository(session).get_by_id(list_id)
    if obj is None:
        raise HTTPException(status_code=404, detail={
            "error": "not_found", "message": f"parsed list {list_id} not found",
        })
    return ParsedListRead.model_validate(obj)


@router.get(
    "/lists/{list_id}/targets",
    response_model=list[ParsedListTargetRead],
)
def list_targets(
    list_id: int,
    session: Session = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    if ParsedListRepository(session).get_by_id(list_id) is None:
        raise HTTPException(status_code=404, detail={
            "error": "not_found", "message": f"parsed list {list_id} not found",
        })
    rows = ParsedListTargetRepository(session).list_by_list(
        list_id, limit=limit, offset=offset,
    )
    return [ParsedListTargetRead.model_validate(r) for r in rows]


@router.delete(
    "/lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT,
)
def delete_list(list_id: int, session: Session = Depends(get_session)):
    if not ParsedListRepository(session).delete_hard(list_id):
        raise HTTPException(status_code=404, detail={
            "error": "not_found", "message": f"parsed list {list_id} not found",
        })
    session.commit()
    return None


@router.post("/lists/run/chat-messages")
async def run_chat_messages(
    body: RunChatMessagesRequest,
    task_queue: TaskQueue = Depends(get_task_queue),
    user_id: str = Depends(require_user),
):
    """Enqueue parser-job. Возвращает job_id — фронт поллит /parse-jobs."""
    job_id = await task_queue.enqueue(
        TaskName.PRIMING_PARSER_RUN,
        "chat_messages",
        {
            "owner_user_id": _owner_id(user_id),
            "name": body.name,
            "collector_account_id": body.collector_account_id,
            "chat_ref": body.chat_ref,
            "days_window": body.days_window,
            "min_messages": body.min_messages,
            "require_username": body.require_username,
            "premium_only": body.premium_only,
        },
    )
    return {"job_id": job_id}


@router.post("/lists/run/chat-members")
async def run_chat_members(
    body: RunChatMembersRequest,
    task_queue: TaskQueue = Depends(get_task_queue),
    user_id: str = Depends(require_user),
):
    job_id = await task_queue.enqueue(
        TaskName.PRIMING_PARSER_RUN,
        "chat_members",
        {
            "owner_user_id": _owner_id(user_id),
            "name": body.name,
            "collector_account_id": body.collector_account_id,
            "chat_ref": body.chat_ref,
            "only_recently_seen": body.only_recently_seen,
            "require_username": body.require_username,
            "premium_only": body.premium_only,
        },
    )
    return {"job_id": job_id}
