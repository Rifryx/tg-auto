"""Pydantic-схемы привязки аккаунта к кампании.

См. docs/neuroshilling-spec.md § 3.5.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from core.schemas.base import ORMModel


class AttachAccountRequest(BaseModel):
    account_id: int
    role_id: Optional[int] = None
    is_reserve: bool = False


class CampaignAccountUpdate(BaseModel):
    role_id: Optional[int] = None
    is_reserve: Optional[bool] = None


class CampaignAccountRead(ORMModel):
    id: int
    campaign_id: int
    account_id: int
    role_id: Optional[int]
    is_reserve: bool
    created_at: datetime
