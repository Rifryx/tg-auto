"""Bulk-action: массово подписаться на набор каналов (этап 8 УТП).

Для КАЖДОГО аккаунта прогоняем список ``channel_refs`` и вступаем/присоединяемся.
Публичные каналы (@name / t.me/name) — ``JoinChannelRequest`` по entity;
инвайты (t.me/+hash / joinchat/hash) — ``ImportChatInviteRequest``.
Если один ref упал, остальные всё равно попробуем — результат по каждому в
``detail.joined`` / ``detail.errors``.

Папки-addlist оставлены на commenting-модуль (там уже есть развёртывание в
дочерние monitored-каналы); здесь фокус — «прямая» подписка на набор ссылок.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from core.enums import BulkActionType
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.health.monitor import around_telethon_call
from worker.telegram_refs import classify_ref, invite_hash, public_ref


class JoinChannelsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_refs: list[str] = Field(min_length=1, max_length=100)


async def _run(
    *,
    account_id: int,
    payload: JoinChannelsPayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    joined: list[str] = []
    errors: dict[str, str] = {}

    for raw in payload.channel_refs:
        kind = classify_ref(raw)
        try:
            if kind == "invite":
                await around_telethon_call(
                    lambda h=invite_hash(raw): client(ImportChatInviteRequest(h)),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
            elif kind == "folder":
                errors[raw] = "folders_unsupported_in_bulk"
                continue
            else:
                entity = await around_telethon_call(
                    lambda r=public_ref(raw): client.get_entity(r),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
                await around_telethon_call(
                    lambda e=entity: client(JoinChannelRequest(e)),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
            joined.append(raw)
        except Exception as exc:  # noqa: BLE001 - фиксируем per-ref
            errors[raw] = repr(exc)

    ok = bool(joined) or not errors
    return BulkActionResult(
        ok=ok,
        detail={"joined": joined, "errors": errors},
    )


register(
    BulkAction(
        name=BulkActionType.JOIN_CHANNELS.value,
        requires_client=True,
        payload_schema=JoinChannelsPayload,
        run=_run,
        title="Подписаться на каналы",
        description="Массово вступает каждым аккаунтом в переданный набор каналов.",
        governor_key="bulk_channel",
    )
)
