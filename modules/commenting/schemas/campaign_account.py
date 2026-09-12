from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from core.schemas.base import ORMModel


class CampaignAccountCreate(BaseModel):
    campaign_id: int
    account_id: int
    override_prompt: Optional[str] = None


class CampaignAccountRead(ORMModel):
    campaign_id: int
    account_id: int
    override_prompt: Optional[str]
    created_at: datetime


class AttachAccountRequest(BaseModel):
    account_id: int
    override_prompt: Optional[str] = None
