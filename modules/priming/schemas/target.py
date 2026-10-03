"""Pydantic-схемы целей кампании (spec §4.3, §6)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field, model_validator

from modules.priming.schemas.common import PrimingBaseModel
from modules.priming.schemas.enums import TargetLastSeen, TargetStatus


class PrimingTargetCreate(PrimingBaseModel):
    """Одна цель. Должно быть заполнено хотя бы одно из
    ``tg_user_id / username / phone``.
    """

    tg_user_id: Optional[int] = Field(default=None, gt=0)
    username: Optional[str] = Field(default=None, min_length=1, max_length=64)
    phone: Optional[str] = Field(default=None, min_length=1, max_length=32)
    has_premium: Optional[bool] = None
    last_seen_bucket: TargetLastSeen = TargetLastSeen.UNKNOWN
    source_id: Optional[int] = None

    @model_validator(mode="after")
    def _identity_required(self) -> "PrimingTargetCreate":
        if not (self.tg_user_id or self.username or self.phone):
            raise ValueError(
                "target must have at least one of tg_user_id / username / phone"
            )
        return self


class PrimingTargetImport(PrimingBaseModel):
    """Массовый импорт целей (JSON или разобранный CSV)."""

    targets: list[PrimingTargetCreate] = Field(..., min_length=1, max_length=100_000)


class PrimingTargetRead(PrimingBaseModel):
    id: int
    campaign_id: int
    source_id: Optional[int] = None
    tg_user_id: Optional[int] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    has_premium: Optional[bool] = None
    last_seen_bucket: TargetLastSeen
    status: TargetStatus
    assigned_account_id: Optional[int] = None
    attempts: int
    last_error_code: Optional[str] = None
    primed_at: Optional[datetime] = None
    created_at: datetime


class PrimingTargetBulkBlacklist(PrimingBaseModel):
    """Пометить перечисленные target_ids как ``blacklisted`` (spec §6)."""

    target_ids: list[int] = Field(..., min_length=1, max_length=10_000)
