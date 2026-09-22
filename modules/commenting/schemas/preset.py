"""Pydantic-схемы пресетов (§ Этап 1)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from core.schemas.base import ORMModel


# --- AccountPreset -----------------------------------------------------------


class AccountPresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    account_ids: list[int] = Field(default_factory=list)


class AccountPresetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    account_ids: Optional[list[int]] = None


class AccountPresetRead(ORMModel):
    id: int
    owner_user_id: str
    name: str
    account_ids: list[int]
    created_at: datetime
    updated_at: datetime


# --- DelayPreset -------------------------------------------------------------


class DelayValues(BaseModel):
    """Общие «числовые» поля пресета — вынесены для reuse в create/update."""

    posting_delay_min_sec: int = Field(ge=0)
    posting_delay_max_sec: int = Field(ge=0)
    join_delay_min_sec: int = Field(ge=0)
    join_delay_max_sec: int = Field(ge=0)
    floodwait_pause_sec: int = Field(ge=0)
    floodwait_quarantine_max: int = Field(ge=1)


class DelayPresetCreate(DelayValues):
    name: str = Field(min_length=1, max_length=64)


class DelayPresetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    posting_delay_min_sec: Optional[int] = Field(default=None, ge=0)
    posting_delay_max_sec: Optional[int] = Field(default=None, ge=0)
    join_delay_min_sec: Optional[int] = Field(default=None, ge=0)
    join_delay_max_sec: Optional[int] = Field(default=None, ge=0)
    floodwait_pause_sec: Optional[int] = Field(default=None, ge=0)
    floodwait_quarantine_max: Optional[int] = Field(default=None, ge=1)


class DelayPresetRead(ORMModel):
    id: int
    owner_user_id: Optional[str]
    name: str
    is_system: bool
    posting_delay_min_sec: int
    posting_delay_max_sec: int
    join_delay_min_sec: int
    join_delay_max_sec: int
    floodwait_pause_sec: int
    floodwait_quarantine_max: int
    created_at: datetime
    updated_at: datetime
