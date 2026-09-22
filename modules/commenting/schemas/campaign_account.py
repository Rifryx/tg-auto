from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from core.schemas.base import ORMModel


class CampaignAccountCreate(BaseModel):
    campaign_id: int
    account_id: int
    override_prompt: Optional[str] = None
    probability_override: Optional[int] = Field(default=None, ge=0, le=100)


class CampaignAccountRead(ORMModel):
    campaign_id: int
    account_id: int
    override_prompt: Optional[str]
    probability_override: Optional[int]
    created_at: datetime


class AttachAccountRequest(BaseModel):
    account_id: int
    override_prompt: Optional[str] = None
    probability_override: Optional[int] = Field(default=None, ge=0, le=100)


class CampaignAccountUpdate(BaseModel):
    """Патч поля пер-аккаунтной привязки (пока — только probability_override)."""

    probability_override: Optional[int] = Field(default=None, ge=0, le=100)
    override_prompt: Optional[str] = None
