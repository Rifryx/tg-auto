"""Bulk-action: «просмотреть» последние N постов каналов (этап 8 УТП).

Что делает:
* для каждого канала из ``channel_refs`` берёт последние ``depth`` сообщений
  (``get_messages(entity, limit=depth)``);
* отмечает их как прочитанные (``send_read_acknowledge``) — счётчик просмотров
  канала растёт на 1 на аккаунт-подписчика.

Используется как «view-boost» и как часть УТП «живой аккаунт»: если акк
подписан на набор каналов, но никогда их не читает, антифрод Telegram может
это заметить. Периодические просмотры делают паттерн естественным.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.enums import BulkActionType
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.health.monitor import around_telethon_call
from worker.telegram_refs import public_ref


class ViewChannelPostsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_refs: list[str] = Field(min_length=1, max_length=50)
    depth: int = Field(default=5, ge=1, le=50)


async def _run(
    *,
    account_id: int,
    payload: ViewChannelPostsPayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    viewed: dict[str, int] = {}
    errors: dict[str, str] = {}

    for raw in payload.channel_refs:
        try:
            entity = await around_telethon_call(
                lambda r=public_ref(raw): client.get_entity(r),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            messages = await around_telethon_call(
                lambda e=entity: client.get_messages(e, limit=payload.depth),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            messages = list(messages or [])
            if messages:
                await around_telethon_call(
                    lambda e=entity, m=messages: client.send_read_acknowledge(
                        e, max_id=m[0].id
                    ),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
            viewed[raw] = len(messages)
        except Exception as exc:  # noqa: BLE001
            errors[raw] = repr(exc)

    return BulkActionResult(
        ok=bool(viewed) or not errors,
        detail={"viewed": viewed, "errors": errors},
    )


register(
    BulkAction(
        name=BulkActionType.VIEW_CHANNEL_POSTS.value,
        requires_client=True,
        payload_schema=ViewChannelPostsPayload,
        run=_run,
        title="Просмотреть каналы",
        description="Каждый аккаунт читает последние N постов из выбранных каналов.",
    )
)
