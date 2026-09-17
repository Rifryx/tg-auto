"""Bulk-действие: назначить/сбросить персону аккаунтам.

Без Telethon-клиента: чистая БД-операция. Валидация: если ``persona_id``
не ``None``, персона должна существовать (проверяется в API до старта).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from core.enums import BulkActionType
from core.repositories.account import AccountRepository
from core.schemas.account import AccountUpdate
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register


class SetPersonaPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: Optional[int] = None


async def _run(
    *,
    account_id: int,
    payload: SetPersonaPayload,
    session_factory,
    **_: object,
) -> BulkActionResult:
    with session_factory() as session:
        account = AccountRepository(session).update(
            account_id, AccountUpdate(persona_id=payload.persona_id)
        )
        session.commit()
    if account is None:
        return BulkActionResult(ok=False, skipped=True, detail={"reason": "not_found"})
    return BulkActionResult(ok=True, detail={"persona_id": payload.persona_id})


register(
    BulkAction(
        name=BulkActionType.SET_PERSONA.value,
        requires_client=False,
        payload_schema=SetPersonaPayload,
        run=_run,
        title="Назначить персону",
        description="Массово устанавливает или снимает персону у выбранных аккаунтов.",
    )
)
