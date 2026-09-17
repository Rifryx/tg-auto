"""Bulk-action: массовый просмотр чужих Stories (этап 9 УТП, «живой аккаунт»).

Для каждого аккаунта проходит по списку ``peer_refs`` (username/приватная ссылка
не работает — только public username, отсюда `public_ref`) и смотрит все
активные stories: ``GetPeerStoriesRequest`` → ``ReadStoriesRequest`` до
последнего id.

Зачем: аккаунт, подписанный на каналы, но никогда не читающий их и не
смотрящий stories, — классический паттерн бота. Периодические просмотры делают
активность естественной для антифрода Telegram.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from telethon.tl.functions.stories import GetPeerStoriesRequest, ReadStoriesRequest

from core.enums import BulkActionType
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.health.monitor import around_telethon_call
from worker.telegram_refs import public_ref


class ViewStoriesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    peer_refs: list[str] = Field(min_length=1, max_length=50)


async def _run(
    *,
    account_id: int,
    payload: ViewStoriesPayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    viewed: dict[str, int] = {}
    errors: dict[str, str] = {}

    for raw in payload.peer_refs:
        try:
            entity = await around_telethon_call(
                lambda r=public_ref(raw): client.get_entity(r),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            peer_stories = await around_telethon_call(
                lambda e=entity: client(GetPeerStoriesRequest(e)),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            stories = list(
                getattr(getattr(peer_stories, "stories", None), "stories", None) or []
            )
            if not stories:
                viewed[raw] = 0
                continue
            max_id = max(s.id for s in stories)
            await around_telethon_call(
                lambda e=entity, mid=max_id: client(
                    ReadStoriesRequest(peer=e, max_id=mid)
                ),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            viewed[raw] = len(stories)
        except Exception as exc:  # noqa: BLE001 — per-ref изоляция
            errors[raw] = repr(exc)

    return BulkActionResult(
        ok=bool(viewed) or not errors,
        detail={"viewed": viewed, "errors": errors},
    )


register(
    BulkAction(
        name=BulkActionType.VIEW_STORIES.value,
        requires_client=True,
        payload_schema=ViewStoriesPayload,
        run=_run,
        title="Просмотреть чужие Stories",
        description="Каждый аккаунт открывает и отмечает прочитанными активные Stories указанных peer'ов.",
    )
)
