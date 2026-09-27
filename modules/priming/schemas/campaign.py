"""Pydantic-схемы кампании прайминга (spec §4.1, §6).

Валидация значений — здесь. Правила видимости/иммутабельности при
``status=running`` (когда почти всё readonly) — на сервисном слое
(промпт 2.4); в схеме мы только помечаем поля Optional в Update,
чтобы сериалайзер не спорил с partial-обновлением.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field, model_validator

from modules.priming.schemas.common import PrimingBaseModel
from modules.priming.schemas.enums import (
    HumanizerMode,
    PrimingCampaignStatus,
    PrimingMode,
    TriggerAction,
    WarmupProfile,
)


class PrimingCampaignCreate(PrimingBaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    mode: PrimingMode = PrimingMode.PRIMING
    trigger_action: TriggerAction

    humanizer_mode: HumanizerMode = HumanizerMode.BALANCED

    delay_between_targets_sec_min: int = Field(default=60, ge=0)
    delay_between_targets_sec_max: int = Field(default=180, ge=0)
    flood_wait_pause_sec: int = Field(default=500, gt=0)
    max_flood_waits_per_account: int = Field(default=3, gt=0)
    daily_limit_per_account: int = Field(default=35, ge=1, le=500)
    warmup_profile: WarmupProfile = WarmupProfile.WARM

    require_username: bool = True
    premium_only: bool = False
    exclude_bots: bool = True
    exclude_deleted: bool = True
    exclude_admins: bool = True

    stop_on_privacy_rate: float = Field(default=0.3, ge=0.0, le=1.0)

    dry_run: bool = False

    created_by: Optional[int] = None

    @model_validator(mode="after")
    def _delay_range_ordered(self) -> "PrimingCampaignCreate":
        if self.delay_between_targets_sec_min > self.delay_between_targets_sec_max:
            raise ValueError(
                "delay_between_targets_sec_min must be <= "
                "delay_between_targets_sec_max"
            )
        return self


class PrimingCampaignUpdate(PrimingBaseModel):
    """Partial-обновление. Все поля Optional; сервисный слой сам решает,
    что нельзя менять в ``running/queued``.
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    trigger_action: Optional[TriggerAction] = None
    humanizer_mode: Optional[HumanizerMode] = None

    delay_between_targets_sec_min: Optional[int] = Field(default=None, ge=0)
    delay_between_targets_sec_max: Optional[int] = Field(default=None, ge=0)
    flood_wait_pause_sec: Optional[int] = Field(default=None, gt=0)
    max_flood_waits_per_account: Optional[int] = Field(default=None, gt=0)
    daily_limit_per_account: Optional[int] = Field(default=None, ge=1, le=500)
    warmup_profile: Optional[WarmupProfile] = None

    require_username: Optional[bool] = None
    premium_only: Optional[bool] = None
    exclude_bots: Optional[bool] = None
    exclude_deleted: Optional[bool] = None
    exclude_admins: Optional[bool] = None

    stop_on_privacy_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    dry_run: Optional[bool] = None

    @model_validator(mode="after")
    def _delay_range_ordered(self) -> "PrimingCampaignUpdate":
        lo, hi = self.delay_between_targets_sec_min, self.delay_between_targets_sec_max
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(
                "delay_between_targets_sec_min must be <= "
                "delay_between_targets_sec_max"
            )
        return self


class PrimingCampaignCounters(PrimingBaseModel):
    """Агрегированные счётчики кампании для UI."""

    accounts_total: int = 0
    accounts_working: int = 0
    accounts_cooldown: int = 0
    accounts_quarantined: int = 0
    targets_total: int = 0
    targets_pending: int = 0
    targets_assigned: int = 0
    targets_primed: int = 0
    targets_failed: int = 0
    targets_blacklisted: int = 0


class PrimingCampaignRead(PrimingBaseModel):
    id: int
    name: str
    mode: PrimingMode
    trigger_action: TriggerAction
    humanizer_mode: HumanizerMode

    delay_between_targets_sec_min: int
    delay_between_targets_sec_max: int
    flood_wait_pause_sec: int
    max_flood_waits_per_account: int
    daily_limit_per_account: int
    warmup_profile: WarmupProfile

    require_username: bool
    premium_only: bool
    exclude_bots: bool
    exclude_deleted: bool
    exclude_admins: bool

    stop_on_privacy_rate: float

    dry_run: bool = False

    status: PrimingCampaignStatus
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    # Nested — заполняется сервисным слоем; в базовом Read остаётся None,
    # чтобы прочитать одну строку из БД можно было без агрегации.
    counters: Optional[PrimingCampaignCounters] = None
