"""API каналов аккаунта (аккаунт-центричный мониторинг).

Каждый аккаунт держит свой список каналов. Разрешение ссылок и реальная
подписка/отписка в Telegram выполняются воркером (см. worker-часть) — здесь
только CRUD над записями и постановка в очередь.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from typing import Optional

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_publisher, get_task_queue
from core.queue import TaskQueue
from core.queue.publisher import Publisher
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from modules.commenting.repositories import MonitoredChannelRepository
from modules.commenting.schemas import AddChannelsRequest, MonitoredChannelRead
from modules.commenting.worker.registry import (
    ACTION_DETACH,
    publish_channel_lifecycle,
)

router = APIRouter(
    prefix="/accounts", tags=["channels"], dependencies=[Depends(require_user)]
)


def _require_account(session: Session, account_id: int) -> None:
    if AccountRepository(session).get(account_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {account_id} not found")


@router.get(
    "/{account_id}/channels", response_model=list[MonitoredChannelRead]
)
def list_channels(
    account_id: int, session: Session = Depends(get_session)
) -> list[MonitoredChannelRead]:
    _require_account(session, account_id)
    rows = MonitoredChannelRepository(session).list_by_account(account_id)
    return [MonitoredChannelRead.model_validate(r) for r in rows]


@router.post(
    "/{account_id}/channels",
    response_model=list[MonitoredChannelRead],
    status_code=status.HTTP_202_ACCEPTED,
)
async def add_channels(
    account_id: int,
    body: AddChannelsRequest,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
) -> list[MonitoredChannelRead]:
    """Добавляет каналы (ссылки/юзернеймы или ссылки на папки) в статусе
    ``pending`` и ставит их на разрешение воркеру (подписка + discussion-группа)."""
    _require_account(session, account_id)
    repo = MonitoredChannelRepository(session)
    created = []
    for ref in body.refs:
        ref = ref.strip()
        if not ref:
            continue
        if repo.get_by_account_input(account_id, ref) is not None:
            continue  # уже добавлен — не дублируем
        created.append(repo.create(account_id, ref, body.is_folder))
    session.commit()
    for row in created:
        await task_queue.enqueue(TaskName.COMMENTING_RESOLVE_CHANNEL, row.id)
    return [MonitoredChannelRead.model_validate(r) for r in created]


@router.delete(
    "/{account_id}/channels/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def remove_channel(
    account_id: int,
    channel_id: int,
    unsubscribe: bool = False,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
    publisher: Optional[Publisher] = Depends(get_publisher),
) -> None:
    """Снимает канал с работы. По умолчанию подписка в Telegram сохраняется;
    ``?unsubscribe=true`` — воркер дополнительно отпишет аккаунт."""
    _require_account(session, account_id)
    repo = MonitoredChannelRepository(session)
    ch = repo.get(channel_id)
    if ch is None or ch.account_id != account_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"channel {channel_id} not found")
    # Данные для отписки снимаем ДО удаления строки.
    ref = ch.channel_ref or ch.input_ref
    tg_id = ch.channel_tg_id
    was_working = ch.status == "working"
    repo.delete(channel_id)
    session.commit()
    # Снять слушатель канала без рестарта воркера (если он был активен).
    if was_working:
        publish_channel_lifecycle(publisher, account_id, channel_id, ACTION_DETACH)
    if unsubscribe:
        await task_queue.enqueue(
            TaskName.COMMENTING_LEAVE_CHANNEL, account_id, ref, tg_id
        )
