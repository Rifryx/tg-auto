"""Bulk-action: массовая публикация Stories (этап 9 УТП).

Payload:
* ``media_b64`` — картинка (обычно 1080×1920, ≤2 МБ) как base64. JSONB payload
  выдержит, но для реально больших медиа лучше сделать asset-store (см. backlog).
* ``caption`` — текст поста (опц.).
* ``privacy`` — ``everybody`` / ``contacts_only`` / ``close_friends`` / ``selected``.
  (``selected`` требует список user_id — сейчас не поддерживаем, вернём 422 в API,
  а здесь просто конвертируем в InputPrivacy*.)
* ``period`` — 21600/43200/86400/172800 (6ч/12ч/24ч/48ч). По умолчанию 86400.

Каждый аккаунт загружает медиа СВОИМ клиентом (через свой прокси) — байты в
payload одни и те же, но загрузка происходит независимо: одно и то же медиа
у Telegram будет висеть под разными storyId, что и нужно.
"""

from __future__ import annotations

import base64
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from telethon.tl.functions.stories import SendStoryRequest
from telethon.tl.types import (
    InputMediaUploadedPhoto,
    InputPrivacyValueAllowAll,
    InputPrivacyValueAllowCloseFriends,
    InputPrivacyValueAllowContacts,
    InputPrivacyValueDisallowAll,
)

from core.enums import BulkActionType
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.health.monitor import around_telethon_call


PrivacyMode = Literal["everybody", "contacts_only", "close_friends", "nobody"]

_PRIVACY_MAP: dict[PrivacyMode, type] = {
    "everybody": InputPrivacyValueAllowAll,
    "contacts_only": InputPrivacyValueAllowContacts,
    "close_friends": InputPrivacyValueAllowCloseFriends,
    "nobody": InputPrivacyValueDisallowAll,
}

_ALLOWED_PERIODS = (21600, 43200, 86400, 172800)


class PublishStoryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_b64: str = Field(min_length=1)
    caption: str = ""
    privacy: PrivacyMode = "everybody"
    period: int = 86400

    def decoded_media(self) -> bytes:
        return base64.b64decode(self.media_b64)


async def _run(
    *,
    account_id: int,
    payload: PublishStoryPayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    if payload.period not in _ALLOWED_PERIODS:
        return BulkActionResult(
            ok=False,
            detail={"reason": "bad_period", "allowed": list(_ALLOWED_PERIODS)},
        )

    try:
        media_bytes = payload.decoded_media()
    except (ValueError, base64.binascii.Error) as exc:
        return BulkActionResult(
            ok=False, detail={"reason": "invalid_media_b64", "error": repr(exc)}
        )

    # 1) загрузить файл своим клиентом (свой прокси)
    uploaded = await around_telethon_call(
        lambda: client.upload_file(media_bytes),
        account_id=account_id,
        session_factory=session_factory,
        publisher=publisher,
    )

    media = InputMediaUploadedPhoto(file=uploaded)
    privacy_cls = _PRIVACY_MAP[payload.privacy]

    result = await around_telethon_call(
        lambda: client(
            SendStoryRequest(
                peer="me",
                media=media,
                privacy_rules=[privacy_cls()],
                random_id=_random_id(),
                caption=payload.caption or None,
                period=payload.period,
            )
        ),
        account_id=account_id,
        session_factory=session_factory,
        publisher=publisher,
    )
    # result — Updates; конкретный story id вытащить не всегда возможно
    # (Telethon возвращает UpdatesTooLong для акков-новичков). Не критично для UI.
    return BulkActionResult(
        ok=True,
        detail={
            "privacy": payload.privacy,
            "period": payload.period,
            "caption_len": len(payload.caption),
            "updates_type": type(result).__name__,
        },
    )


def _random_id() -> int:
    """random_id для SendStoryRequest: signed int64 (Telegram сам дедупает)."""
    import secrets

    return secrets.randbits(63)


register(
    BulkAction(
        name=BulkActionType.PUBLISH_STORY.value,
        requires_client=True,
        payload_schema=PublishStoryPayload,
        run=_run,
        title="Опубликовать Stories",
        description="Массовая публикация одной истории от лица каждого выбранного аккаунта.",
    )
)
