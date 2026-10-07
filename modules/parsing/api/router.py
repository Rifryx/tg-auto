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
from modules.parsing.list_ops import ListOpError, run_list_op
from modules.parsing.repositories import (
    ParsedCommunityItemRepository,
    ParsedListRepository,
    ParsedListTargetRepository,
)
from modules.parsing.schemas import (
    ListOpRequest,
    ParsedCommunityItemRead,
    ParsedListRead,
    ParsedListTargetRead,
    RunChannelCommentersRequest,
    RunChatMembersRequest,
    RunChatMessagesRequest,
    RunCommunitiesRequest,
    RunDiscoverRequest,
    RunPostReactorsRequest,
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


# Поля фильтров, общие для всех run-запросов (Extraction+, этап 1).
_FILTER_KEYS = (
    "require_username",
    "premium_only",
    "require_photo",
    "verified_only",
    "exclude_scam_fake",
    "require_phone_visible",
    "username_regex",
    "name_script",
    "last_seen_max_days",
)


def _filter_payload(body) -> dict:
    return {k: getattr(body, k) for k in _FILTER_KEYS}


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
    "/lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None,
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
            **_filter_payload(body),
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
            **_filter_payload(body),
        },
    )
    return {"job_id": job_id}


@router.post("/lists/run/channel-commenters")
async def run_channel_commenters(
    body: RunChannelCommentersRequest,
    task_queue: TaskQueue = Depends(get_task_queue),
    user_id: str = Depends(require_user),
):
    """Комментаторы канала (из его linked discussion chat)."""
    job_id = await task_queue.enqueue(
        TaskName.PRIMING_PARSER_RUN,
        "channel_commenters",
        {
            "owner_user_id": _owner_id(user_id),
            "name": body.name,
            "collector_account_id": body.collector_account_id,
            "chat_ref": body.chat_ref,
            "days_window": body.days_window,
            "min_messages": body.min_messages,
            **_filter_payload(body),
        },
    )
    return {"job_id": job_id}


@router.post("/lists/run/post-reactors")
async def run_post_reactors(
    body: RunPostReactorsRequest,
    task_queue: TaskQueue = Depends(get_task_queue),
    user_id: str = Depends(require_user),
):
    """Пользователи, ставившие реакции на последние посты канала/чата."""
    job_id = await task_queue.enqueue(
        TaskName.PRIMING_PARSER_RUN,
        "post_reactors",
        {
            "owner_user_id": _owner_id(user_id),
            "name": body.name,
            "collector_account_id": body.collector_account_id,
            "chat_ref": body.chat_ref,
            "posts_limit": body.posts_limit,
            "reactions_per_post": body.reactions_per_post,
            "min_reactions": body.min_reactions,
            **_filter_payload(body),
        },
    )
    return {"job_id": job_id}


@router.post("/lists/run/communities")
async def run_communities(
    body: RunCommunitiesRequest,
    task_queue: TaskQueue = Depends(get_task_queue),
    user_id: str = Depends(require_user),
):
    """Discovery сообществ: обогащение переданных ссылок (каналы/чаты) + фильтры."""
    job_id = await task_queue.enqueue(
        TaskName.PRIMING_PARSER_RUN,
        "communities",
        {
            "owner_user_id": _owner_id(user_id),
            "name": body.name,
            "collector_account_id": body.collector_account_id,
            "refs": body.refs,
            "kind": body.kind,
            "min_participants": body.min_participants,
            "max_participants": body.max_participants,
            "require_public": body.require_public,
            "require_linked_chat": body.require_linked_chat,
            "last_post_max_days": body.last_post_max_days,
            "exclude_scam_fake": body.exclude_scam_fake,
            "verified_only": body.verified_only,
            "title_regex": body.title_regex,
            "username_regex": body.username_regex,
        },
    )
    return {"job_id": job_id}


@router.post("/lists/run/discover")
async def run_discover(
    body: RunDiscoverRequest,
    task_queue: TaskQueue = Depends(get_task_queue),
    user_id: str = Depends(require_user),
):
    """Бесплатный нативный discovery сообществ: глобальный поиск + «похожие
    каналы» Telegram + snowball (рекомендации/форварды/упоминания) → обогащение
    и фильтрация. Без внешних сервисов."""
    job_id = await task_queue.enqueue(
        TaskName.PRIMING_PARSER_RUN,
        "discover_communities",
        {
            "owner_user_id": _owner_id(user_id),
            "name": body.name,
            "collector_account_id": body.collector_account_id,
            "seeds": body.seeds,
            "term": body.term,
            "use_search": body.use_search,
            "use_recommendations": body.use_recommendations,
            "use_forwards": body.use_forwards,
            "use_mentions": body.use_mentions,
            "depth": body.depth,
            "max_results": body.max_results,
            "kind": body.kind,
            "min_participants": body.min_participants,
            "max_participants": body.max_participants,
            "require_public": body.require_public,
            "require_linked_chat": body.require_linked_chat,
            "last_post_max_days": body.last_post_max_days,
            "exclude_scam_fake": body.exclude_scam_fake,
            "verified_only": body.verified_only,
            "title_regex": body.title_regex,
            "username_regex": body.username_regex,
        },
    )
    return {"job_id": job_id}


@router.get("/lists/{list_id}/communities", response_model=list[ParsedCommunityItemRead])
def list_communities(
    list_id: int,
    session: Session = Depends(get_session),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    if ParsedListRepository(session).get_by_id(list_id) is None:
        raise HTTPException(status_code=404, detail={
            "error": "not_found", "message": f"parsed list {list_id} not found",
        })
    rows = ParsedCommunityItemRepository(session).list_by_list(
        list_id, limit=limit, offset=offset,
    )
    return [ParsedCommunityItemRead.model_validate(r) for r in rows]


@router.post("/lists/ops", response_model=ParsedListRead, status_code=status.HTTP_201_CREATED)
def list_ops(
    body: ListOpRequest,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
):
    """Операции над списками (пересечение/объединение/вычитание/сэмпл).

    Синхронно (чистый DB, без Telegram): создаёт новый производный список."""
    try:
        result = run_list_op(
            session,
            owner_user_id=_owner_id(user_id),
            name=body.name,
            op=body.op,
            source_list_ids=body.source_list_ids,
            min_overlap=body.min_overlap,
            sample_size=body.sample_size,
        )
    except ListOpError as exc:
        raise HTTPException(status_code=422, detail={
            "error": "invalid_list_op", "message": str(exc),
        }) from exc
    obj = ParsedListRepository(session).get_by_id(result.list_id)
    return ParsedListRead.model_validate(obj)
