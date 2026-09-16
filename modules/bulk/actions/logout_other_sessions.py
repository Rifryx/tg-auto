"""Bulk-действие: сбросить чужие сессии Telegram у выбранных аккаунтов.

Полезно после импорта партии сессий: убираем «висящие» устройства с серверов
Telegram, оставляя только собственный клиент. Требует Telethon-клиента.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from telethon.tl.functions.auth import ResetAuthorizationsRequest

from core.enums import BulkActionType
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.health.monitor import around_telethon_call


class LogoutOtherSessionsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


async def _run(
    *,
    account_id: int,
    payload: LogoutOtherSessionsPayload,  # noqa: ARG001 — payload пустой
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    await around_telethon_call(
        lambda: client(ResetAuthorizationsRequest()),
        account_id=account_id,
        session_factory=session_factory,
        publisher=publisher,
    )
    return BulkActionResult(ok=True, detail={"logged_out_others": True})


register(
    BulkAction(
        name=BulkActionType.LOGOUT_OTHER_SESSIONS.value,
        requires_client=True,
        payload_schema=LogoutOtherSessionsPayload,
        run=_run,
        title="Сбросить чужие сессии",
        description="Terminate all sessions except this client's on Telegram servers.",
    )
)
