"""Bulk-action: управление постами в канале, созданном аккаунтом
(«Управление выбранным аккаунтом», этап 1).

Работает поверх каналов из ``project_channels`` (их создаёт ``create_channel``).
Одним действием покрывает публикацию и сопровождение постов — для одного
аккаунта (``account_ids=[id]``) из карточки аккаунта, либо массово.

Payload:
* ``channel_tg_id`` — id канала (из ``project_channels``);
* ``channel_access_hash`` — access_hash того же канала (если известен —
  строим ``InputChannel`` без лишнего резолва; иначе падаем на ``PeerChannel``);
* ``mode``:
  * ``send`` — отправить пост (``text`` обязателен), опц. ``pin_after_send``;
  * ``pin`` / ``unpin`` — (от)закрепить сообщение ``message_id``;
  * ``delete`` — удалить сообщение ``message_id``.

Поле ``pinned_message_id`` в ``project_channels`` синхронизируется с реальным
состоянием (send+pin / pin → id, unpin → None).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from telethon.tl.functions.channels import DeleteChannelRequest, EditPhotoRequest
from telethon.tl.functions.messages import UpdatePinnedMessageRequest
from telethon.tl.types import InputChannel, InputChatUploadedPhoto, PeerChannel

from core.enums import BulkActionType
from core.repositories.media_asset import MediaAssetRepository
from core.repositories.project_channel import ProjectChannelRepository
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.health.monitor import around_telethon_call


class ManageChannelPostPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_tg_id: int
    channel_access_hash: Optional[int] = None
    mode: Literal[
        "send", "pin", "unpin", "delete", "set_photo", "delete_channel"
    ] = "send"
    text: Optional[str] = Field(default=None, max_length=4096)
    message_id: Optional[int] = None
    pin_after_send: bool = False
    # Для mode=set_photo — новый аватар канала/чата (media_assets.id).
    photo_media_id: Optional[int] = None

    @model_validator(mode="after")
    def _validate_mode(self) -> "ManageChannelPostPayload":
        if self.mode == "send":
            if not (self.text and self.text.strip()):
                raise ValueError("mode=send requires non-empty text")
        elif self.mode in ("pin", "unpin", "delete"):
            if self.message_id is None:
                raise ValueError(f"mode={self.mode} requires message_id")
        elif self.mode == "set_photo":
            if self.photo_media_id is None:
                raise ValueError("mode=set_photo requires photo_media_id")
        # delete_channel не требует дополнительных полей
        return self


def _peer(payload: ManageChannelPostPayload):
    """InputChannel при наличии access_hash, иначе PeerChannel (резолв клиентом)."""
    if payload.channel_access_hash is not None:
        return InputChannel(payload.channel_tg_id, payload.channel_access_hash)
    return PeerChannel(payload.channel_tg_id)


async def _run(
    *,
    account_id: int,
    payload: ManageChannelPostPayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    peer = _peer(payload)

    # Резолвим сущность один раз — нужна и для send, и для pin/delete.
    try:
        entity = await around_telethon_call(
            lambda: client.get_entity(peer),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
    except Exception as exc:  # noqa: BLE001
        return BulkActionResult(
            ok=False, detail={"reason": "channel_resolve_failed", "error": repr(exc)}
        )

    new_pinned: Optional[int] = None  # что записать в project_channels (если надо)
    touch_pinned = False
    detail: dict[str, object] = {"mode": payload.mode}

    try:
        if payload.mode == "send":
            sent = await around_telethon_call(
                lambda: client.send_message(entity, payload.text),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            msg_id = int(getattr(sent, "id", 0)) or None
            detail["message_id"] = msg_id
            if payload.pin_after_send and msg_id is not None:
                await around_telethon_call(
                    lambda: client(
                        UpdatePinnedMessageRequest(peer=entity, id=msg_id)
                    ),
                    account_id=account_id,
                    session_factory=session_factory,
                    publisher=publisher,
                )
                new_pinned, touch_pinned = msg_id, True
                detail["pinned"] = True

        elif payload.mode in ("pin", "unpin"):
            pinned = payload.mode == "pin"
            await around_telethon_call(
                lambda: client(
                    UpdatePinnedMessageRequest(
                        peer=entity, id=payload.message_id, unpin=not pinned
                    )
                ),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            new_pinned = payload.message_id if pinned else None
            touch_pinned = True
            detail["message_id"] = payload.message_id
            detail["pinned"] = pinned

        elif payload.mode == "delete":
            await around_telethon_call(
                lambda: client.delete_messages(entity, [payload.message_id]),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            detail["message_id"] = payload.message_id
            detail["deleted"] = True

        elif payload.mode == "set_photo":
            # Новый аватар канала/чата из media_assets.
            with session_factory() as session:
                asset = MediaAssetRepository(session).get(payload.photo_media_id)
                if asset is None:
                    return BulkActionResult(
                        ok=False,
                        detail={
                            "reason": "media_not_found",
                            "photo_media_id": payload.photo_media_id,
                        },
                    )
                photo_bytes = asset.bytes
                photo_name = asset.filename or f"photo_{asset.id}"
            uploaded = await around_telethon_call(
                lambda: client.upload_file(photo_bytes, file_name=photo_name),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            await around_telethon_call(
                lambda: client(
                    EditPhotoRequest(
                        channel=entity, photo=InputChatUploadedPhoto(file=uploaded)
                    )
                ),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            detail["photo_set"] = True

        else:  # delete_channel — удалить канал/чат целиком + убрать из списка
            await around_telethon_call(
                lambda: client(DeleteChannelRequest(channel=entity)),
                account_id=account_id,
                session_factory=session_factory,
                publisher=publisher,
            )
            with session_factory() as session:
                ProjectChannelRepository(session).delete_by_account_tg(
                    account_id, payload.channel_tg_id
                )
                session.commit()
            detail["channel_deleted"] = True
    except Exception as exc:  # noqa: BLE001
        return BulkActionResult(
            ok=False, detail={"reason": f"{payload.mode}_failed", "error": repr(exc)}
        )

    # Синхронизируем pinned_message_id в нашей БД (если операция его затронула).
    if touch_pinned:
        with session_factory() as session:
            repo = ProjectChannelRepository(session)
            obj = repo.find_by_account_tg(account_id, payload.channel_tg_id)
            if obj is not None:
                obj.pinned_message_id = new_pinned
                session.commit()

    return BulkActionResult(ok=True, detail=detail)


register(
    BulkAction(
        name=BulkActionType.MANAGE_CHANNEL_POST.value,
        requires_client=True,
        payload_schema=ManageChannelPostPayload,
        run=_run,
        title="Управление постами канала",
        description=(
            "Публикация, закрепление/открепление и удаление постов в канале, "
            "созданном аккаунтом (project_channels)."
        ),
        governor_key="bulk_channel",
    )
)
