"""Транзакционные операции attach/detach аккаунта к кампании (§1.2, §10).

Смена статуса аккаунта — только через :class:`AccountStateMachine`. attach и
запись в ``campaign_accounts`` идут в ОДНОЙ транзакции: строка привязки
вставляется до перехода, а ``transition`` коммитит всё вместе; любая ошибка →
rollback (аккаунт не «повисает» в assigned без привязки и наоборот).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.enums import AccountStatus, Initiator
from core.queue.publisher import Publisher
from core.repositories.account import AccountRepository
from core.state_machine import AccountEvent, AccountStateMachine, TransitionError
from modules.commenting.models import CampaignAccount
from modules.commenting.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
)
from modules.commenting.schemas import CampaignAccountCreate

CONTAINER_TYPE = "commenting"


class CommentingNotFound(Exception):
    """Кампания или аккаунт не найдены (→ 404)."""


class CommentingConflict(Exception):
    """Недопустимое состояние для операции (→ 409)."""


def attach_account(
    session: Session,
    publisher: Optional[Publisher],
    campaign_id: int,
    account_id: int,
    override_prompt: Optional[str] = None,
    probability_override: Optional[int] = None,
) -> CampaignAccount:
    if CampaignRepository(session).get(campaign_id) is None:
        raise CommentingNotFound(f"campaign {campaign_id} not found")

    account = AccountRepository(session).get(account_id)
    if account is None:
        raise CommentingNotFound(f"account {account_id} not found")
    # 'pool' исключает cooldown/banned/assigned/warming/etc.
    if account.status != AccountStatus.POOL.value:
        raise CommentingConflict(
            f"account {account_id} is '{account.status}', must be 'pool' to attach"
        )
    # Эксклюзивность: аккаунт не должен быть уже привязан (UNIQUE account_id).
    if CampaignAccountRepository(session).get_by_account(account_id) is not None:
        raise CommentingConflict(f"account {account_id} is already attached to a campaign")

    try:
        CampaignAccountRepository(session).create(
            CampaignAccountCreate(
                campaign_id=campaign_id,
                account_id=account_id,
                override_prompt=override_prompt,
                probability_override=probability_override,
            )
        )
        # transition коммитит всю транзакцию (вставку + смену статуса).
        AccountStateMachine(session, publisher).transition(
            account_id,
            AccountEvent.CONTAINER_ATTACH,
            Initiator.USER,
            meta={"container_type": CONTAINER_TYPE, "container_id": campaign_id},
        )
    except (TransitionError, IntegrityError) as exc:
        session.rollback()
        raise CommentingConflict(str(exc)) from exc

    return CampaignAccountRepository(session).get(campaign_id, account_id)


def detach_account(
    session: Session,
    publisher: Optional[Publisher],
    campaign_id: int,
    account_id: int,
) -> None:
    link = CampaignAccountRepository(session).get(campaign_id, account_id)
    if link is None:
        raise CommentingNotFound(
            f"account {account_id} is not attached to campaign {campaign_id}"
        )
    try:
        CampaignAccountRepository(session).delete(campaign_id, account_id)
        AccountStateMachine(session, publisher).transition(
            account_id, AccountEvent.CONTAINER_DETACH, Initiator.USER
        )
    except (TransitionError, LookupError) as exc:
        session.rollback()
        raise CommentingConflict(str(exc)) from exc
