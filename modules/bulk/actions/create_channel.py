"""Bulk-action: массово создать канал/супергруппу от лица каждого аккаунта
(этап 8, backlog #3).

Payload:
* ``title`` (1..255) — название;
* ``about`` (0..255) — описание;
* ``is_megagroup`` — создать супергруппу вместо канала;
* ``project_id`` — привязать к проекту (опц., проверяется API-слоем);
* ``pin_first_post`` — тело первого поста и просьба закрепить (опц.).

Каждый аккаунт создаёт СВОЙ канал; результат пишется в ``project_channels``
(dedup по (account_id, channel_tg_id) — повторный запуск не плодит копии).

Если ``pin_first_post`` задан:
1. отправляем сообщение в свежесозданный канал;
2. ``UpdatePinnedMessageRequest(pinned=True)`` на его id;
3. в БД сохраняем ``pinned_message_id``.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from telethon.tl.functions.channels import (
    CreateChannelRequest,
    UpdateUsernameRequest,
)
from telethon.tl.functions.messages import UpdatePinnedMessageRequest
from telethon.tl.types import InputChannel

from core.enums import BulkActionType
from core.repositories.project_channel import ProjectChannelRepository
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.health.monitor import around_telethon_call


class CreateChannelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    about: str = Field(default="", max_length=255)
    is_megagroup: bool = False
    # Публичный канал/чат → задаётся @username (t.me/username). Иначе приватный
    # (только пригласительная ссылка). username: 5–32 символа, буква в начале.
    is_public: bool = False
    public_username: Optional[str] = Field(
        default=None, pattern=r"^[a-zA-Z][a-zA-Z0-9_]{4,31}$"
    )
    project_id: Optional[int] = None
    pin_first_post: Optional[str] = Field(default=None, max_length=4096)


def _extract_created_channel(updates) -> tuple[int, Optional[int], Optional[str]]:
    """Достаём (channel_id, access_hash, username) из ответа CreateChannel.

    Telegram отвечает ``Updates`` с полем ``chats``: первый — новый канал.
    """
    chats = getattr(updates, "chats", None) or []
    if not chats:
        raise RuntimeError("CreateChannelRequest returned no chats")
    channel = chats[0]
    return (
        int(getattr(channel, "id", 0)),
        getattr(channel, "access_hash", None),
        getattr(channel, "username", None),
    )


def _extract_message_id(updates) -> Optional[int]:
    """Первый ``id`` сообщения из ``updates`` (для pin)."""
    for upd in getattr(updates, "updates", None) or []:
        msg = getattr(upd, "message", None)
        if msg is not None and getattr(msg, "id", None) is not None:
            return int(msg.id)
    # SendMessage вернуть может UpdateShortSentMessage — обрабатываем и его.
    if getattr(updates, "id", None) is not None:
        try:
            return int(updates.id)
        except (TypeError, ValueError):
            return None
    return None


async def _run(
    *,
    account_id: int,
    payload: CreateChannelPayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    # 1) Создаём канал/супергруппу.
    updates = await around_telethon_call(
        lambda: client(
            CreateChannelRequest(
                title=payload.title,
                about=payload.about,
                megagroup=payload.is_megagroup,
            )
        ),
        account_id=account_id,
        session_factory=session_factory,
        publisher=publisher,
    )
    try:
        channel_id, access_hash, username = _extract_created_channel(updates)
    except RuntimeError as exc:
        return BulkActionResult(
            ok=False, detail={"reason": "no_channel_in_response", "error": repr(exc)}
        )

    # 1.5) Публичный → выставляем @username. Если не вышло (занят/невалиден) —
    # канал остаётся приватным, фиксируем ошибку в detail (канал уже создан).
    username_error: Optional[str] = None
    if payload.is_public and payload.public_username:
        try:
            await around_telethon_call(
                lambda: client(
                    UpdateUsernameRequest(
                        channel=InputChannel(channel_id, access_hash or 0),
                        username=payload.public_username,
                    )
                ),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            username = payload.public_username
        except Exception as exc:  # noqa: BLE001 — username не критичен для create
            username_error = repr(exc)

    # 2) Дедуп: если такой канал у аккаунта уже есть — пишем возвращённые
    # поля, но новую строку не создаём.
    with session_factory() as session:
        repo = ProjectChannelRepository(session)
        existing = repo.find_by_account_tg(account_id, channel_id)
        if existing is not None:
            return BulkActionResult(
                ok=True,
                skipped=True,
                detail={
                    "reason": "already_created",
                    "channel_tg_id": channel_id,
                    "id": existing.id,
                },
            )

    # 3) Опционально: пост первым сообщением + pin.
    pinned_message_id: Optional[int] = None
    if payload.pin_first_post:
        # SendMessage через high-level Telethon API — сам разберётся с peer.
        try:
            entity = await around_telethon_call(
                lambda: client.get_entity(channel_id),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            sent = await around_telethon_call(
                lambda: client.send_message(entity, payload.pin_first_post),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            msg_id = int(getattr(sent, "id", 0)) or None
            if msg_id is not None:
                await around_telethon_call(
                    lambda: client(
                        UpdatePinnedMessageRequest(
                            peer=entity, id=msg_id, pinned=True,
                        )
                    ),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
                pinned_message_id = msg_id
        except Exception as exc:  # noqa: BLE001 — pin не критичен для create
            # Канал создан, но pin не удался — фиксируем факт и продолжаем.
            with session_factory() as session:
                ProjectChannelRepository(session).create(
                    account_id=account_id,
                    project_id=payload.project_id,
                    channel_tg_id=channel_id,
                    channel_access_hash=access_hash,
                    title=payload.title,
                    username=username,
                    is_megagroup=payload.is_megagroup,
                    pinned_message_id=None,
                )
                session.commit()
            return BulkActionResult(
                ok=True,
                detail={
                    "channel_tg_id": channel_id,
                    "username": username,
                    "pin_error": repr(exc),
                },
            )

    with session_factory() as session:
        obj = ProjectChannelRepository(session).create(
            account_id=account_id,
            project_id=payload.project_id,
            channel_tg_id=channel_id,
            channel_access_hash=access_hash,
            title=payload.title,
            username=username,
            is_megagroup=payload.is_megagroup,
            pinned_message_id=pinned_message_id,
        )
        session.commit()

    detail: dict[str, object] = {
        "id": obj.id,
        "channel_tg_id": channel_id,
        "username": username,
        "pinned_message_id": pinned_message_id,
    }
    if username_error is not None:
        detail["username_error"] = username_error
    return BulkActionResult(ok=True, detail=detail)


register(
    BulkAction(
        name=BulkActionType.CREATE_CHANNEL.value,
        requires_client=True,
        payload_schema=CreateChannelPayload,
        run=_run,
        title="Создать канал",
        description=(
            "Каждый аккаунт создаёт СВОЙ канал (или супергруппу) с указанными "
            "названием/описанием, опционально закрепляет первый пост. Записывается "
            "в project_channels — можно потом фильтровать по проекту."
        ),
        governor_key="bulk_channel",
    )
)
