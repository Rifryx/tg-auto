"""Pydantic-схемы кампании (Create/Read/Update).

См. docs/neuroshilling-spec.md § 3.1.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from core.schemas.base import ORMModel

LLMProvider = Literal["deepseek", "gemini"]
CampaignStatus = Literal["draft", "ready", "running", "paused", "completed", "error"]
AutoResponderMode = Literal["off", "neuro_dialogs", "reply_in_chat"]


class _DelayRangesMixin:
    """Общие валидаторы диапазонов задержек — используются и в Create, и в Update."""

    @model_validator(mode="after")
    def _check_delay_ranges(self):
        mn = getattr(self, "reply_delay_min_sec", None)
        mx = getattr(self, "reply_delay_max_sec", None)
        if mn is not None and mx is not None and mn > mx:
            raise ValueError("reply_delay_min_sec must be <= reply_delay_max_sec")
        tmn = getattr(self, "target_delay_min_sec", None)
        tmx = getattr(self, "target_delay_max_sec", None)
        if tmn is not None and tmx is not None and tmn > tmx:
            raise ValueError("target_delay_min_sec must be <= target_delay_max_sec")
        return self


class CampaignCreate(BaseModel, _DelayRangesMixin):
    name: str = Field(min_length=1)
    brand_name: Optional[str] = None
    brand_link: Optional[str] = None
    topic: Optional[str] = None

    llm_provider: LLMProvider = "deepseek"
    unique_messages: bool = True
    use_chat_context: bool = True

    reply_delay_min_sec: int = Field(default=5, ge=0)
    reply_delay_max_sec: int = Field(default=15, ge=0)
    target_delay_min_sec: int = Field(default=600, ge=0)
    target_delay_max_sec: int = Field(default=1800, ge=0)
    posts_per_target: int = Field(default=1, ge=1)

    scenario_id: Optional[int] = None
    media_asset_id: Optional[int] = None

    auto_responder: AutoResponderMode = "off"
    reserve_enabled: bool = True

    msg_limit_per_hour: Optional[int] = Field(default=None, gt=0)
    msg_limit_total: Optional[int] = Field(default=None, gt=0)

    enabled: bool = True


class CampaignUpdate(BaseModel, _DelayRangesMixin):
    name: Optional[str] = Field(default=None, min_length=1)
    brand_name: Optional[str] = None
    brand_link: Optional[str] = None
    topic: Optional[str] = None

    llm_provider: Optional[LLMProvider] = None
    unique_messages: Optional[bool] = None
    use_chat_context: Optional[bool] = None

    reply_delay_min_sec: Optional[int] = Field(default=None, ge=0)
    reply_delay_max_sec: Optional[int] = Field(default=None, ge=0)
    target_delay_min_sec: Optional[int] = Field(default=None, ge=0)
    target_delay_max_sec: Optional[int] = Field(default=None, ge=0)
    posts_per_target: Optional[int] = Field(default=None, ge=1)

    scenario_id: Optional[int] = None
    media_asset_id: Optional[int] = None

    auto_responder: Optional[AutoResponderMode] = None
    reserve_enabled: Optional[bool] = None

    msg_limit_per_hour: Optional[int] = Field(default=None, gt=0)
    msg_limit_total: Optional[int] = Field(default=None, gt=0)

    enabled: Optional[bool] = None
    status: Optional[CampaignStatus] = None


class CampaignRead(ORMModel):
    id: int
    name: str
    brand_name: Optional[str]
    brand_link: Optional[str]
    topic: Optional[str]
    llm_provider: LLMProvider
    unique_messages: bool
    use_chat_context: bool
    reply_delay_min_sec: int
    reply_delay_max_sec: int
    target_delay_min_sec: int
    target_delay_max_sec: int
    posts_per_target: int
    scenario_id: Optional[int]
    media_asset_id: Optional[int]
    auto_responder: AutoResponderMode
    reserve_enabled: bool
    msg_limit_per_hour: Optional[int]
    msg_limit_total: Optional[int]
    enabled: bool
    status: CampaignStatus
    created_at: datetime
    updated_at: datetime
