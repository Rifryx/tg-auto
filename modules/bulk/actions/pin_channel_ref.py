"""Bulk-действие: закрепить/открепить ПРОИЗВОЛЬНЫЙ канал как "личный канал"
(Personal Channel) на ПУБЛИЧНОМ профиле аккаунта.

ВАЖНО: это НЕ закрепление в списке диалогов самого аккаунта (то, что видит
только владелец) — это официальная функция Telegram "Personal Channel",
карточка которого отображается в профиле аккаунта всем, кто его открывает
(как у каналов вида "RIFRYX PROJECT" на реальных профилях). Работает на
обычных (не Premium) аккаунтах — ограничение Premium на эту функцию не
распространяется.

API: account.updatePersonalChannel(channel) — https://core.telegram.org/method/account.updatePersonalChannel
Требование Telegram: канал должен быть именно broadcast-каналом (не супергруппой),
иначе придёт ошибка PUBLIC_BROADCAST_EXPECTED.

Принимает ЛЮБУЮ ссылку/@username канала, на который у аккаунта есть доступ,
резолвит его и устанавливает/снимает как personal channel.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from telethon.tl.functions.account import UpdatePersonalChannelRequest
from telethon.tl.types import InputChannelEmpty

from core.enums import BulkActionType
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.health.monitor import around_telethon_call


class PinChannelRefPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # @username, t.me/… ссылка или пригласительная ссылка на канал.
    # Не обязателен, если pinned=False (тогда просто снимаем текущий personal channel).
    ref: Optional[str] = Field(default=None, max_length=256)
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
    # Снятие personal channel — ref не нужен, просто передаём пустой InputChannel.
    if not payload.pinned:
        try:
            await around_telethon_call(
                lambda: client(UpdatePersonalChannelRequest(channel=InputChannelEmpty())),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
        except Exception as exc:  # noqa: BLE001
            return BulkActionResult(
                ok=False, detail={"reason": "unpin_failed", "error": repr(exc)}
            )
        return BulkActionResult(ok=True, detail={"pinned": False})

    ref = (payload.ref or "").strip()
    if not ref:
        return BulkActionResult(
            ok=False, detail={"reason": "ref_required", "error": "ref is required when pinned=True"}
        )

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

    # Personal channel принимает только broadcast-канал, не супергруппу/чат —
    # проверяем заранее, чтобы дать понятную ошибку вместо PUBLIC_BROADCAST_EXPECTED.
    is_broadcast = bool(getattr(entity, "broadcast", False))
    if not is_broadcast:
        return BulkActionResult(
            ok=False,
            detail={
                "reason": "not_a_broadcast_channel",
                "ref": ref,
                "error": "Personal channel поддерживает только broadcast-каналы, не чаты/супергруппы",
            },
        )

    try:
        input_channel = await around_telethon_call(
            lambda: client.get_input_entity(entity),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
        await around_telethon_call(
            lambda: client(UpdatePersonalChannelRequest(channel=input_channel)),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
    except Exception as exc:  # noqa: BLE001
        return BulkActionResult(
            ok=False, detail={"reason": "pin_failed", "ref": ref, "error": repr(exc)}
        )

    username = getattr(entity, "username", None)
    title = getattr(entity, "title", None) or ref
    link: Optional[str] = f"https://t.me/{username}" if username else None
    return BulkActionResult(
        ok=True,
        detail={
            "pinned": True,
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
        title="Закрепить канал на публичном профиле",
        description=(
            "Устанавливает/снимает произвольный broadcast-канал (по @username/ссылке) "
            "как Personal Channel — карточка канала, видимая всем на публичном профиле "
            "аккаунта. Не требует Telegram Premium."
        ),
        governor_key="bulk_channel",
    )
)
