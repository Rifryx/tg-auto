"""Роутер модуля парсинга (промпт 3.2b).

Префикс ``/modules/parsing``. CRUD-читатель для списков + endpoint
запуска парсера. Сам парсер (Telethon-heavy) вызывается из worker'а
через arq-задачу; здесь только создание list-заготовки и enqueue.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
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
    ParsingJobRepository,
)
from modules.parsing.schemas import (
    ListOpRequest,
    ParsedCommunityItemRead,
    ParsedListRead,
    ParsedListTargetRead,
    ParsingJobControl,
    ParsingJobRead,
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
    "phone_country_prefixes",
)


def _filter_payload(body) -> dict:
    return {k: getattr(body, k) for k in _FILTER_KEYS}


# Поля фильтров для community-парсеров (enrich + discover).
_COMMUNITY_FILTER_KEYS = (
    "kind",
    "min_participants",
    "max_participants",
    "require_public",
    "require_linked_chat",
    "last_post_max_days",
    "exclude_scam_fake",
    "verified_only",
    "title_regex",
    "username_regex",
    "title_exclude_regex",
    "language",
    "allow_noforwards",
    "min_slowmode_seconds",
    "max_slowmode_seconds",
)


def _community_filter_payload(body) -> dict:
    return {k: getattr(body, k) for k in _COMMUNITY_FILTER_KEYS}


async def _start_job(
    *,
    session: Session,
    task_queue: TaskQueue,
    user_id: str,
    kind: str,
    name: str,
    payload: dict,
) -> dict:
    """Создаёт запись parsing.jobs и ставит задачу в очередь.

    Возвращает ``{"job_id": <id записи>}`` — UI поллит прогресс по нему.
    В payload воркеру кладём ``job_id``, чтобы он вёл живой прогресс/управление.
    """
    owner = _owner_id(user_id)
    job = ParsingJobRepository(session).create(
        owner_user_id=owner, kind=kind, name=name, params=payload
    )
    session.commit()
    full_payload = {**payload, "owner_user_id": owner, "name": name, "job_id": job.id}
    await task_queue.enqueue(TaskName.PRIMING_PARSER_RUN, kind, full_payload)
    return {"job_id": job.id}


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


class DeleteTargetsBody(BaseModel):
    target_ids: list[int] = Field(..., min_length=1, max_length=5000)


@router.post("/lists/{list_id}/targets/delete")
def delete_targets(
    list_id: int,
    body: DeleteTargetsBody,
    session: Session = Depends(get_session),
):
    """Удаляет выбранные строки списка и пересчитывает счётчик.

    Жалоба: «в базе нет возможности удалять спаршеных». Поддерживает пакетное
    удаление (несколько id за раз)."""
    if ParsedListRepository(session).get_by_id(list_id) is None:
        raise HTTPException(status_code=404, detail={
            "error": "not_found", "message": f"parsed list {list_id} not found",
        })
    target_repo = ParsedListTargetRepository(session)
    removed = target_repo.delete_targets(list_id, body.target_ids)
    remaining = target_repo.count_by_list(list_id)
    # after_filters_count = реальное число строк в списке после удаления.
    ParsedListRepository(session).update(list_id, {"after_filters_count": remaining})
    session.commit()
    return {"removed": removed, "remaining": remaining}


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
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
    user_id: str = Depends(require_user),
):
    """Создаёт задачу парсинга и возвращает её job_id — фронт поллит прогресс."""
    return await _start_job(
        session=session, task_queue=task_queue, user_id=user_id,
        kind="chat_messages", name=body.name,
        payload={
            "collector_account_id": body.collector_account_id,
            "chat_ref": body.chat_ref,
            "days_window": body.days_window,
            "min_messages": body.min_messages,
            "max_targets": body.max_targets,
            **_filter_payload(body),
        },
    )


@router.post("/lists/run/chat-members")
async def run_chat_members(
    body: RunChatMembersRequest,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
    user_id: str = Depends(require_user),
):
    return await _start_job(
        session=session, task_queue=task_queue, user_id=user_id,
        kind="chat_members", name=body.name,
        payload={
            "collector_account_id": body.collector_account_id,
            "chat_ref": body.chat_ref,
            "only_recently_seen": body.only_recently_seen,
            "max_targets": body.max_targets,
            **_filter_payload(body),
        },
    )


@router.post("/lists/run/channel-commenters")
async def run_channel_commenters(
    body: RunChannelCommentersRequest,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
    user_id: str = Depends(require_user),
):
    """Комментаторы канала (из его linked discussion chat)."""
    return await _start_job(
        session=session, task_queue=task_queue, user_id=user_id,
        kind="channel_commenters", name=body.name,
        payload={
            "collector_account_id": body.collector_account_id,
            "chat_ref": body.chat_ref,
            "days_window": body.days_window,
            "min_messages": body.min_messages,
            "max_targets": body.max_targets,
            **_filter_payload(body),
        },
    )


@router.post("/lists/run/post-reactors")
async def run_post_reactors(
    body: RunPostReactorsRequest,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
    user_id: str = Depends(require_user),
):
    """Пользователи, ставившие реакции на последние посты канала/чата."""
    return await _start_job(
        session=session, task_queue=task_queue, user_id=user_id,
        kind="post_reactors", name=body.name,
        payload={
            "collector_account_id": body.collector_account_id,
            "chat_ref": body.chat_ref,
            "posts_limit": body.posts_limit,
            "reactions_per_post": body.reactions_per_post,
            "min_reactions": body.min_reactions,
            "max_targets": body.max_targets,
            **_filter_payload(body),
        },
    )


@router.post("/lists/run/communities")
async def run_communities(
    body: RunCommunitiesRequest,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
    user_id: str = Depends(require_user),
):
    """Discovery сообществ: обогащение переданных ссылок (каналы/чаты) + фильтры."""
    return await _start_job(
        session=session, task_queue=task_queue, user_id=user_id,
        kind="communities", name=body.name,
        payload={
            "collector_account_id": body.collector_account_id,
            "refs": body.refs,
            **_community_filter_payload(body),
        },
    )


@router.post("/lists/run/discover")
async def run_discover(
    body: RunDiscoverRequest,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
    user_id: str = Depends(require_user),
):
    """Бесплатный нативный discovery сообществ: глобальный поиск + «похожие
    каналы» Telegram + snowball (рекомендации/форварды/упоминания) → обогащение
    и фильтрация. Без внешних сервисов."""
    return await _start_job(
        session=session, task_queue=task_queue, user_id=user_id,
        kind="discover_communities", name=body.name,
        payload={
            "collector_account_id": body.collector_account_id,
            "seeds": body.seeds,
            "term": body.term,
            "use_search": body.use_search,
            "use_recommendations": body.use_recommendations,
            "use_forwards": body.use_forwards,
            "use_mentions": body.use_mentions,
            "depth": body.depth,
            "max_results": body.max_results,
            **_community_filter_payload(body),
        },
    )


# ── Задачи парсинга: прогресс и управление (пауза/стоп) ──────────────────────


@router.get("/jobs", response_model=list[ParsingJobRead])
def list_jobs(
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
):
    rows = ParsingJobRepository(session).list_by_owner(_owner_id(user_id))
    return [ParsingJobRead.model_validate(r) for r in rows]


@router.get("/jobs/{job_id}", response_model=ParsingJobRead)
def get_job(
    job_id: int,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
):
    job = ParsingJobRepository(session).get(job_id)
    if job is None or job.owner_user_id != _owner_id(user_id):
        raise HTTPException(status_code=404, detail={
            "error": "not_found", "message": f"parsing job {job_id} not found",
        })
    return ParsingJobRead.model_validate(job)


@router.post("/jobs/{job_id}/control", response_model=ParsingJobRead)
def control_job(
    job_id: int,
    body: ParsingJobControl,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
):
    """Управление задачей: pause | resume | stop. Воркер читает флаг по ходу."""
    repo = ParsingJobRepository(session)
    job = repo.get(job_id)
    if job is None or job.owner_user_id != _owner_id(user_id):
        raise HTTPException(status_code=404, detail={
            "error": "not_found", "message": f"parsing job {job_id} not found",
        })
    control = {"pause": "pause", "resume": "run", "stop": "stop"}.get(body.action)
    if control is None:
        raise HTTPException(status_code=422, detail={
            "error": "bad_action", "message": "action must be pause|resume|stop",
        })
    repo.set_control(job_id, control)
    session.commit()
    return ParsingJobRead.model_validate(repo.get(job_id))


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
