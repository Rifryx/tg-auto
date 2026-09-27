"""Pydantic-схемы anchor-каналов (spec §4.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from modules.priming.schemas.common import PrimingBaseModel
from modules.priming.schemas.enums import AnchorChannelState


class AnchorChannelCreate(PrimingBaseModel):
    account_id: int
    channel_tg_id: int
    title: str = Field(..., min_length=1, max_length=120)
    is_public: bool = False
    pinned_post_id: Optional[int] = None
    pinned_post_text: Optional[str] = None
    state: AnchorChannelState = AnchorChannelState.OK


class AnchorChannelUpdate(PrimingBaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    is_public: Optional[bool] = None
    pinned_post_id: Optional[int] = None
    pinned_post_text: Optional[str] = None
    state: Optional[AnchorChannelState] = None


class AnchorChannelRead(PrimingBaseModel):
    id: int
    account_id: int
    channel_tg_id: int
    title: str
    is_public: bool
    pinned_post_id: Optional[int] = None
    pinned_post_text: Optional[str] = None
    attached_to_profile_at: Optional[datetime] = None
    state: AnchorChannelState
    created_at: datetime
    updated_at: datetime
