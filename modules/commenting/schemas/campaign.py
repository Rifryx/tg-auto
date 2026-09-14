from datetime import datetime, time
from typing import Optional

from pydantic import BaseModel

from core.enums import LLMProvider
from core.schemas.base import ORMModel


class CampaignCreate(BaseModel):
    name: str
    # Легаси: каналы теперь живут на аккаунтах, кампания — просто папка. Поле
    # оставлено опциональным для обратной совместимости старого слушателя.
    target_channel: Optional[str] = None
    base_system_prompt: str
    llm_provider: LLMProvider
    active_hours_start: time
    active_hours_end: time
    active_hours_tz: str
    posting_delay_min_sec: int
    posting_delay_max_sec: int
    discussion_group_id: Optional[int] = None
    enabled: bool = True


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    target_channel: Optional[str] = None
    base_system_prompt: Optional[str] = None
    llm_provider: Optional[LLMProvider] = None
    active_hours_start: Optional[time] = None
    active_hours_end: Optional[time] = None
    active_hours_tz: Optional[str] = None
    posting_delay_min_sec: Optional[int] = None
    posting_delay_max_sec: Optional[int] = None
    discussion_group_id: Optional[int] = None
    enabled: Optional[bool] = None


class CampaignRead(ORMModel):
    id: int
    name: str
    target_channel: Optional[str]
    discussion_group_id: Optional[int]
    base_system_prompt: str
    llm_provider: LLMProvider
    active_hours_start: time
    active_hours_end: time
    active_hours_tz: str
    posting_delay_min_sec: int
    posting_delay_max_sec: int
    enabled: bool
    created_at: datetime
    updated_at: datetime
