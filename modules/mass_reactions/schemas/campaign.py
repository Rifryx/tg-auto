"""Pydantic-схемы API модуля масс-реакций."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MassReactionCampaignCreate(_Base):
    name: str = Field(min_length=1, max_length=120)
    reaction_emojis: list[str] = Field(min_length=1)
    chat_source_mode: str = "by_subscriptions"
    reaction_strategy: str = "random"
    every_n_message: int = Field(default=1, ge=1, le=50)
    probability_percent: int = Field(default=100, ge=1, le=100)
    first_n_in_burst: int = Field(default=3, ge=1, le=10)
    duration_hours: int = Field(default=24, ge=1, le=72)
    skip_messages_older_than_days: int = Field(default=1, ge=0, le=30)
    delay_between_reactions_sec_min: int = Field(default=60, ge=0)
    delay_between_reactions_sec_max: int = Field(default=300, ge=0)
    join_pause_sec: int = Field(default=120, ge=0)
    warmup_profile: str = "warm"
    humanizer_mode: str = "balanced"
    daily_limit_per_account: int = Field(default=200, ge=1, le=500)
    max_chats_per_account: int = Field(default=5, ge=1, le=20)
    flood_wait_pause_sec: int = Field(default=3600, gt=0)
    max_flood_waits_per_account: int = Field(default=3, gt=0)
    quiet_hours_start: int = Field(default=0, ge=0, lt=24)
    quiet_hours_end: int = Field(default=24, gt=0, le=24)


class MassReactionCampaignUpdate(_Base):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    reaction_emojis: Optional[list[str]] = Field(default=None, min_length=1)
    chat_source_mode: Optional[str] = None
    reaction_strategy: Optional[str] = None
    every_n_message: Optional[int] = Field(default=None, ge=1, le=50)
    probability_percent: Optional[int] = Field(default=None, ge=1, le=100)
    first_n_in_burst: Optional[int] = Field(default=None, ge=1, le=10)
    duration_hours: Optional[int] = Field(default=None, ge=1, le=72)
    skip_messages_older_than_days: Optional[int] = Field(default=None, ge=0, le=30)
    delay_between_reactions_sec_min: Optional[int] = Field(default=None, ge=0)
    delay_between_reactions_sec_max: Optional[int] = Field(default=None, ge=0)
    join_pause_sec: Optional[int] = Field(default=None, ge=0)
    warmup_profile: Optional[str] = None
    humanizer_mode: Optional[str] = None
    daily_limit_per_account: Optional[int] = Field(default=None, ge=1, le=500)
    max_chats_per_account: Optional[int] = Field(default=None, ge=1, le=20)
    flood_wait_pause_sec: Optional[int] = Field(default=None, gt=0)
    max_flood_waits_per_account: Optional[int] = Field(default=None, gt=0)
    quiet_hours_start: Optional[int] = Field(default=None, ge=0, lt=24)
    quiet_hours_end: Optional[int] = Field(default=None, gt=0, le=24)


class MassReactionCampaignRead(_Base):
    id: int
    name: str
    status: str
    chat_source_mode: str
    reaction_emojis: list[str]
    reaction_strategy: str
    every_n_message: int
    probability_percent: int
    first_n_in_burst: int
    duration_hours: int
    skip_messages_older_than_days: int
    delay_between_reactions_sec_min: int
    delay_between_reactions_sec_max: int
    join_pause_sec: int
    warmup_profile: str
    humanizer_mode: str
    daily_limit_per_account: int
    max_chats_per_account: int
    flood_wait_pause_sec: int
    max_flood_waits_per_account: int
    quiet_hours_start: int
    quiet_hours_end: int
    started_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class MassReactionChatRead(_Base):
    id: int
    chat_ref: str
    chat_tg_id: Optional[int] = None
    title: Optional[str] = None
    state: str
    notify_mode: str
    account_id: Optional[int] = None
    reactions_total: int


class MassReactionAccountRead(_Base):
    id: int
    account_id: int
    state: str
    reactions_today: int
    reactions_total: int


class AddChatsBody(_Base):
    raw_text: str
    notify_mode: str = "notify_only"


class AddAccountsBody(_Base):
    account_ids: list[int] = Field(min_length=1)
