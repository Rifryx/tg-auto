"""Bulk-action: массово создать канал/супергруппу от лица каждого аккаунта
(этап 8, backlog #3).

Payload:
* ``title`` (1..255) — название;
* ``about`` (0..255) — описание;
* ``is_megagroup`` — создать супергруппу вместо канала;
* ``project_id`` — привязать к проекту (опц., проверяется API-слоем);
* ``first_post`` — текст первого поста (опц.), с markdown-разметкой эффектов;
* ``first_post_media_id`` — media_assets.id для медиа-поста (опц.);
* ``first_post_markdown`` — трактовать текст как markdown (по умолч. да);
* ``first_post_pin`` — закрепить первый пост (по умолч. да).

Каждый аккаунт создаёт СВОЙ канал; результат пишется в ``project_channels``
(dedup по (account_id, channel_tg_id) — повторный запуск не плодит копии).

Если задан текст и/или медиа первого поста:
1. (опц.) заливаем медиа и отправляем пост с подписью/текстом; эффекты
   (жирный/курсив/спойлер/…) — через собранные вручную ``formatting_entities``;
2. при ``first_post_pin`` — ``UpdatePinnedMessageRequest(pinned=True)`` на его id;
3. в БД сохраняем ``pinned_message_id`` (если закрепили).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from telethon.tl.functions.channels import (
    CreateChannelRequest,
    EditPhotoRequest,
    TogglePreHistoryHiddenRequest,
    UpdateUsernameRequest,
)
from telethon.tl.functions.messages import (
    ExportChatInviteRequest,
    SetChatAvailableReactionsRequest,
    UpdatePinnedMessageRequest,
)
from telethon.tl.types import (
    ChatReactionsAll,
    ChatReactionsNone,
    InputChannel,
    InputChatUploadedPhoto,
    InputPeerChannel,
)

from core.enums import BulkActionType
from core.repositories.media_asset import MediaAssetRepository
from core.repositories.project_channel import ProjectChannelRepository
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from modules.bulk.text_format import markdown_to_entities
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
    # Супергруппа: скрыть историю чата для новых участников.
    hide_prehistory: bool = False
    # Разрешить реакции (по умолчанию да).
    enable_reactions: bool = True
    # Фото канала/чата (media_assets.id) — опционально.
    photo_media_id: Optional[int] = None
    project_id: Optional[int] = None
    # Первый пост: текст (с markdown-эффектами) и/или медиа, закреплять ли.
    first_post: Optional[str] = Field(default=None, max_length=4096)
    first_post_media_id: Optional[int] = None
    first_post_markdown: bool = True
    first_post_pin: bool = True


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

    ch_input = InputChannel(channel_id, access_hash or 0)
    peer_input = InputPeerChannel(channel_id, access_hash or 0)

    # 1.6) Скрыть историю для новых участников (только супергруппа).
    if payload.is_megagroup and payload.hide_prehistory:
        try:
            await around_telethon_call(
                lambda: client(
                    TogglePreHistoryHiddenRequest(channel=ch_input, enabled=True)
                ),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
        except Exception:  # noqa: BLE001 — не критично для create
            pass

    # 1.7) Реакции (вкл/выкл).
    try:
        reactions = ChatReactionsAll() if payload.enable_reactions else ChatReactionsNone()
        await around_telethon_call(
            lambda: client(
                SetChatAvailableReactionsRequest(
                    peer=peer_input, available_reactions=reactions
                )
            ),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
    except Exception:  # noqa: BLE001
        pass

    # 1.75) Фото канала/чата (из media_assets) — опционально.
    photo_set = False
    if payload.photo_media_id is not None:
        try:
            with session_factory() as session:
                asset = MediaAssetRepository(session).get(payload.photo_media_id)
                photo_bytes = asset.bytes if asset is not None else None
                photo_name = (
                    (asset.filename or f"photo_{asset.id}") if asset is not None else None
                )
            if photo_bytes is not None:
                uploaded_photo = await around_telethon_call(
                    lambda: client.upload_file(photo_bytes, file_name=photo_name),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
                await around_telethon_call(
                    lambda: client(
                        EditPhotoRequest(
                            channel=ch_input,
                            photo=InputChatUploadedPhoto(file=uploaded_photo),
                        )
                    ),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
                photo_set = True
        except Exception:  # noqa: BLE001 — фото не критично для create
            pass

    # 1.8) Инвайт-ссылка для приватных (у публичных есть @username).
    invite_link: Optional[str] = None
    if not payload.is_public:
        try:
            inv = await around_telethon_call(
                lambda: client(ExportChatInviteRequest(peer=peer_input)),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            invite_link = getattr(inv, "link", None)
        except Exception:  # noqa: BLE001
            pass

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

    # 3) Опционально: первый пост (текст и/или медиа) + закрепление.
    text = (payload.first_post or "").strip()
    has_post = bool(text) or payload.first_post_media_id is not None
    pinned_message_id: Optional[int] = None
    post_error: Optional[str] = None
    if has_post:
        try:
            # Эффекты (жирный/курсив/спойлер/…) — собранными вручную entities.
            entities = None
            if text and payload.first_post_markdown:
                text, entities = markdown_to_entities(text)

            entity = await around_telethon_call(
                lambda: client.get_entity(channel_id),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )

            if payload.first_post_media_id is not None:
                with session_factory() as session:
                    asset = MediaAssetRepository(session).get(
                        payload.first_post_media_id
                    )
                    if asset is None:
                        raise RuntimeError(
                            f"media_asset {payload.first_post_media_id} not found"
                        )
                    media_bytes = asset.bytes
                    media_name = asset.filename or f"media_{asset.id}"
                uploaded = await around_telethon_call(
                    lambda: client.upload_file(media_bytes, file_name=media_name),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
                sent = await around_telethon_call(
                    lambda: client.send_file(
                        entity,
                        file=uploaded,
                        caption=text or "",
                        formatting_entities=entities or None,
                        force_document=False,
                    ),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
            else:
                sent = await around_telethon_call(
                    lambda: client.send_message(
                        entity, text, formatting_entities=entities or None
                    ),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )

            msg_id = int(getattr(sent, "id", 0)) or None
            if msg_id is not None and payload.first_post_pin:
                await around_telethon_call(
                    lambda: client(
                        UpdatePinnedMessageRequest(peer=entity, id=msg_id)
                    ),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
                pinned_message_id = msg_id
        except Exception as exc:  # noqa: BLE001 — пост не критичен для create
            # Канал создан, пост/закрепление не удалось — фиксируем и продолжаем.
            post_error = repr(exc)

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
            invite_link=invite_link,
        )
        session.commit()

    detail: dict[str, object] = {
        "id": obj.id,
        "channel_tg_id": channel_id,
        "username": username,
        "invite_link": invite_link,
        "pinned_message_id": pinned_message_id,
        "photo_set": photo_set,
    }
    if username_error is not None:
        detail["username_error"] = username_error
    if post_error is not None:
        detail["post_error"] = post_error
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
