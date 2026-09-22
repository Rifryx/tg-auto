"""Bulk-действие: применить готовый набор полей профиля к выборке аккаунтов.

Payload — тот, что уже прошёл валидацию в API (напр. после preview из
``generate_profile``). Отдельно от ``generate_and_apply_profile`` нужен, чтобы
пользователь мог посмотреть результат генерации на одном акке, отредактировать
и применить массово.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from core.enums import BulkActionType
from core.repositories.account import AccountRepository
from core.schemas.account import AccountUpdate
from modules.bulk.actions.registry import BulkAction, BulkActionResult, register
from modules.profiles.generator import BIO_MAX, NAME_MAX, USERNAME_RE
from worker.profiles.apply import apply_profile_to_telegram


class ApplyProfilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    bio: Optional[str] = None
    username_candidates: list[str] = []

    @field_validator("first_name", "last_name")
    @classmethod
    def _v_names(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if len(v) > NAME_MAX:
            raise ValueError(f"name too long: {len(v)} > {NAME_MAX}")
        return v

    @field_validator("bio")
    @classmethod
    def _v_bio(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if len(v) > BIO_MAX:
            raise ValueError(f"bio too long: {len(v)} > {BIO_MAX}")
        return v

    @field_validator("username_candidates")
    @classmethod
    def _v_usernames(cls, v: list[str]) -> list[str]:
        for u in v:
            if not USERNAME_RE.match(u):
                raise ValueError(f"bad username: {u!r}")
        return v


async def _run(
    *,
    account_id: int,
    payload: ApplyProfilePayload,
    session_factory,
    publisher,
    client,
    **_: object,
) -> BulkActionResult:
    if all(v is None for v in (payload.first_name, payload.last_name, payload.bio)) and \
            not payload.username_candidates:
        return BulkActionResult(ok=False, skipped=True, detail={"reason": "empty_payload"})

    result = await apply_profile_to_telegram(
        client,
        account_id=account_id,
        session_factory=session_factory,
        publisher=publisher,
        first_name=payload.first_name,
        last_name=payload.last_name,
        bio=payload.bio,
        username_candidates=payload.username_candidates or None,
    )

    # Синхронизируем нашу БД с реальным состоянием (то, что действительно
    # применилось — берём из ProfileApplyResult, а не из payload'а).
    with session_factory() as session:
        updates: dict[str, object] = {}
        if payload.first_name is not None and result.updated_names:
            updates["first_name"] = payload.first_name
        if payload.last_name is not None and result.updated_names:
            updates["last_name"] = payload.last_name
        if payload.bio is not None and result.updated_bio:
            updates["bio"] = payload.bio
        if result.applied_username is not None:
            updates["username"] = result.applied_username
        if updates:
            AccountRepository(session).update(account_id, AccountUpdate(**updates))
            session.commit()

    return BulkActionResult(ok=True, detail=result.as_dict())


register(
    BulkAction(
        name=BulkActionType.APPLY_PROFILE.value,
        requires_client=True,
        payload_schema=ApplyProfilePayload,
        run=_run,
        title="Применить оформление профиля",
        description="Единым payload'ом обновляет имя, био и username у выбранных аккаунтов.",
        governor_key="bulk_profile",
    )
)
