"""API каналов аккаунта (аккаунт-центричный мониторинг).

Каждый аккаунт держит свой список каналов. Разрешение ссылок и реальная
подписка/отписка в Telegram выполняются воркером (см. worker-часть) — здесь
только CRUD над записями и постановка в очередь.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from core.repositories.account import AccountRepository
from modules.commenting.repositories import MonitoredChannelRepository
from modules.commenting.schemas import AddChannelsRequest, MonitoredChannelRead

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
def add_channels(
    account_id: int,
    body: AddChannelsRequest,
    session: Session = Depends(get_session),
) -> list[MonitoredChannelRead]:
    """Добавляет каналы (ссылки/юзернеймы или ссылки на папки) в статусе
    ``pending``. Разрешение и подписку выполняет воркер."""
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
    return [MonitoredChannelRead.model_validate(r) for r in created]


@router.delete(
    "/{account_id}/channels/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def remove_channel(
    account_id: int,
    channel_id: int,
    unsubscribe: bool = False,
    session: Session = Depends(get_session),
) -> None:
    """Снимает канал с работы. По умолчанию подписка в Telegram сохраняется;
    ``?unsubscribe=true`` — воркер дополнительно отпишет аккаунт."""
    _require_account(session, account_id)
    repo = MonitoredChannelRepository(session)
    ch = repo.get(channel_id)
    if ch is None or ch.account_id != account_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"channel {channel_id} not found")
    # unsubscribe=true обрабатывается воркером (отписка), затем удаление; сейчас
    # снимаем с работы удалением записи (подписка в Telegram остаётся).
    repo.delete(channel_id)
    session.commit()
