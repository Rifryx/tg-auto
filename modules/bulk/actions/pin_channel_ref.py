"""Bulk-действие: закрепить/открепить ПРОИЗВОЛЬНЫЙ канал/чат в диалогах аккаунта.

В отличие от ``manage_channel_post`` (работает только с созданными приложением
каналами из ``project_channels``), это действие принимает ЛЮБУЮ ссылку/@username
канала или чата, на который у аккаунта есть доступ, резолвит его и
закрепляет/открепляет в списке диалогов (``ToggleDialogPinRequest``).

Возвращает в detail название, @username и ссылку (t.me/username для публичных) —
чтобы UI сразу показал ссылку на закреплённый канал/чат.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from telethon.tl.functions.messages import ToggleDialogPinRequest
from telethon.tl.types import InputDialogPeer

from core.enums import BulkActionType
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.health.monitor import around_telethon_call


class PinChannelRefPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # @username, t.me/… ссылка или пригласительная ссылка на канал/чат.
    ref: str = Field(min_length=1, max_length=256)
    pinned: bool = True


async def _run(
    *,
    account_id: int,
    payload: PinChannelRefPayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    ref = payload.ref.strip()
    try:
        entity = await around_telethon_call(
            lambda: client.get_entity(ref),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
    except Exception as exc:  # noqa: BLE001
        return BulkActionResult(
            ok=False, detail={"reason": "resolve_failed", "ref": ref, "error": repr(exc)}
        )

    try:
        input_peer = await around_telethon_call(
            lambda: client.get_input_entity(entity),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
        await around_telethon_call(
            lambda: client(
                ToggleDialogPinRequest(
                    peer=InputDialogPeer(peer=input_peer), pinned=payload.pinned
                )
            ),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
    except Exception as exc:  # noqa: BLE001
        return BulkActionResult(
            ok=False, detail={"reason": "pin_failed", "ref": ref, "error": repr(exc)}
        )

    username = getattr(entity, "username", None)
    title = (
        getattr(entity, "title", None)
        or getattr(entity, "first_name", None)
        or ref
    )
    link: Optional[str] = f"https://t.me/{username}" if username else None
    return BulkActionResult(
        ok=True,
        detail={
            "pinned": payload.pinned,
            "title": title,
            "username": username,
            "link": link,
        },
    )


register(
    BulkAction(
        name=BulkActionType.PIN_CHANNEL_REF.value,
        requires_client=True,
        payload_schema=PinChannelRefPayload,
        run=_run,
        title="Закрепить канал/чат в аккаунте",
        description=(
            "Закрепляет/открепляет произвольный канал или чат (по @username/ссылке) "
            "в списке диалогов аккаунта."
        ),
        governor_key="bulk_channel",
    )
)
