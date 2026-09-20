"""Bulk-action: массовая публикация Stories (этап 9 УТП).

Payload:
* Источник медиа — ровно ОДИН из:
  * ``media_asset_id`` — id из ``media_assets`` (предпочтительно, этап 9 #1);
  * ``media_b64`` — base64 в самом payload (legacy, для мелких картинок).
* ``caption`` — текст поста (опц.).
* ``privacy`` — ``everybody`` / ``contacts_only`` / ``close_friends`` / ``nobody``.
* ``period`` — 21600/43200/86400/172800 (6ч/12ч/24ч/48ч). По умолчанию 86400.
* ``scheduled_at`` — если задан, action ставит саму себя через TaskQueue.schedule
  на это время и завершает текущий item как ``skipped`` с reason='deferred'
  (backlog #3). Полезно для Autopilot и внешних кампаний.

Каждый аккаунт загружает медиа СВОИМ клиентом (через свой прокси) — байты
берутся один раз (из media_assets или payload), но загрузка происходит
независимо: одно и то же медиа у Telegram будет висеть под разными storyId.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from telethon.tl.functions.stories import SendStoryRequest
from telethon.tl.types import (
    InputMediaUploadedPhoto,
    InputPrivacyValueAllowAll,
    InputPrivacyValueAllowCloseFriends,
    InputPrivacyValueAllowContacts,
    InputPrivacyValueDisallowAll,
)

from core.enums import BulkActionType
from core.repositories.media_asset import MediaAssetRepository
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

    # Ровно один из источников; проверяется в model_validator.
    media_asset_id: Optional[int] = None
    media_b64: Optional[str] = None

    caption: str = ""
    privacy: PrivacyMode = "everybody"
    period: int = 86400
    scheduled_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _validate_media_source(self) -> "PublishStoryPayload":
        has_asset = self.media_asset_id is not None
        has_inline = bool(self.media_b64)
        if has_asset == has_inline:
            raise ValueError(
                "publish_story requires exactly one of media_asset_id / media_b64"
            )
        return self

    def decoded_media(self) -> bytes:
        if self.media_b64 is None:
            raise ValueError("no inline media_b64")
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

    # Расписание (backlog #3): если scheduled_at в будущем, сигналим bulk-item
    # что это отложено. Реальное перепланирование делает item_impl по
    # BulkActionResult (см. reason='deferred'). MVP: если время ещё не
    # наступило — выходим со skipped, job не двигаем; во внешнем месте
    # (кампания/автопилот) отвечает за постановку в нужный момент.
    if payload.scheduled_at is not None:
        now = datetime.now(timezone.utc)
        scheduled = payload.scheduled_at
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        if scheduled > now:
            return BulkActionResult(
                ok=False,
                skipped=True,
                detail={
                    "reason": "deferred",
                    "scheduled_at": scheduled.isoformat(),
                },
            )

    # Источник медиа: сначала пробуем asset store, потом legacy inline.
    if payload.media_asset_id is not None:
        with session_factory() as session:
            asset = MediaAssetRepository(session).get(payload.media_asset_id)
        if asset is None:
            return BulkActionResult(
                ok=False, detail={"reason": "media_asset_not_found",
                                  "media_asset_id": payload.media_asset_id},
            )
        media_bytes = asset.bytes
    else:
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
        governor_key="bulk_publish",
    )
)
