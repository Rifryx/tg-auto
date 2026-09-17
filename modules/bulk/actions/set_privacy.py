"""Bulk-действие: массовая настройка приватности аккаунтов.

Payload задаёт правила видимости (кому виден номер, фото, last_seen и т.д.):
* ``phone``, ``last_seen``, ``photo``, ``forwards``, ``chat_invite``, ``calls``;
* значение — одно из ``"everybody"`` / ``"contacts"`` / ``"nobody"``.

Telethon API: ``account.SetPrivacyRequest`` с соответствующим ``InputPrivacyKey*``.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator
from telethon.tl.functions.account import SetPrivacyRequest
from telethon.tl.types import (
    InputPrivacyKeyChatInvite,
    InputPrivacyKeyForwards,
    InputPrivacyKeyPhoneCall,
    InputPrivacyKeyPhoneNumber,
    InputPrivacyKeyProfilePhoto,
    InputPrivacyKeyStatusTimestamp,
    InputPrivacyValueAllowAll,
    InputPrivacyValueAllowContacts,
    InputPrivacyValueDisallowAll,
)

from core.enums import BulkActionType
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from worker.health.monitor import around_telethon_call


_KEY_MAP: dict[str, type] = {
    "phone": InputPrivacyKeyPhoneNumber,
    "last_seen": InputPrivacyKeyStatusTimestamp,
    "photo": InputPrivacyKeyProfilePhoto,
    "forwards": InputPrivacyKeyForwards,
    "chat_invite": InputPrivacyKeyChatInvite,
    "calls": InputPrivacyKeyPhoneCall,
}
_VALUE_MAP: dict[str, type] = {
    "everybody": InputPrivacyValueAllowAll,
    "contacts": InputPrivacyValueAllowContacts,
    "nobody": InputPrivacyValueDisallowAll,
}


class SetPrivacyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: Optional[str] = None
    last_seen: Optional[str] = None
    photo: Optional[str] = None
    forwards: Optional[str] = None
    chat_invite: Optional[str] = None
    calls: Optional[str] = None

    @field_validator("phone", "last_seen", "photo", "forwards", "chat_invite", "calls")
    @classmethod
    def _validate_value(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in _VALUE_MAP:
            raise ValueError(
                f"privacy value must be one of {sorted(_VALUE_MAP)}, got {v!r}"
            )
        return v

    def as_rules(self) -> list[tuple[type, type]]:
        rules: list[tuple[type, type]] = []
        for field, value in self.model_dump().items():
            if value is None:
                continue
            rules.append((_KEY_MAP[field], _VALUE_MAP[value]))
        return rules


async def _run(
    *,
    account_id: int,
    payload: SetPrivacyPayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    rules = payload.as_rules()
    if not rules:
        return BulkActionResult(ok=False, skipped=True, detail={"reason": "empty_payload"})

    applied: list[str] = []
    for key_cls, value_cls in rules:
        await around_telethon_call(
            lambda k=key_cls, v=value_cls: client(
                SetPrivacyRequest(key=k(), rules=[v()])
            ),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
        )
        applied.append(key_cls.__name__)
    return BulkActionResult(ok=True, detail={"applied": applied})


register(
    BulkAction(
        name=BulkActionType.SET_PRIVACY.value,
        requires_client=True,
        payload_schema=SetPrivacyPayload,
        run=_run,
        title="Настройки приватности",
        description="Массово применяет одинаковый набор правил приватности к выбранным аккаунтам.",
    )
)
