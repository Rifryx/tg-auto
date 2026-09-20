"""Bulk-action: массово отписаться от набора каналов (этап 8 УТП).

Отписка best-effort: каждая ошибка на конкретной ссылке не прерывает весь
item, попадает в ``detail.errors``. Полезно для очистки старых массивных
подписок при переориентации аккаунтов на новый проект.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from telethon.tl.functions.channels import LeaveChannelRequest

from core.enums import BulkActionType
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.health.monitor import around_telethon_call
from worker.telegram_refs import public_ref


class LeaveChannelsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_refs: list[str] = Field(min_length=1, max_length=100)


async def _run(
    *,
    account_id: int,
    payload: LeaveChannelsPayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    left: list[str] = []
    errors: dict[str, str] = {}
    for raw in payload.channel_refs:
        try:
            entity = await around_telethon_call(
                lambda r=public_ref(raw): client.get_entity(r),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            await around_telethon_call(
                lambda e=entity: client(LeaveChannelRequest(e)),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            left.append(raw)
        except Exception as exc:  # noqa: BLE001
            errors[raw] = repr(exc)
    return BulkActionResult(
        ok=bool(left) or not errors,
        detail={"left": left, "errors": errors},
    )


register(
    BulkAction(
        name=BulkActionType.LEAVE_CHANNELS.value,
        requires_client=True,
        payload_schema=LeaveChannelsPayload,
        run=_run,
        title="Отписаться от каналов",
        description="Массово отписывает выбранные аккаунты от набора каналов.",
        governor_key="bulk_channel",
    )
)
