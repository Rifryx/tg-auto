from datetime import datetime, time
from typing import Optional

from pydantic import BaseModel

from core.enums import CommentStatus, LLMProvider
from core.schemas.base import ORMModel


class CampaignCreate(BaseModel):
    name: str
    target_channel: str
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
    target_channel: str
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


class CampaignAccountCreate(BaseModel):
    campaign_id: int
    account_id: int
    override_prompt: Optional[str] = None


class CampaignAccountUpdate(BaseModel):
    override_prompt: Optional[str] = None


class CampaignAccountRead(ORMModel):
    campaign_id: int
    account_id: int
    override_prompt: Optional[str]
    created_at: datetime


class CommentLogCreate(BaseModel):
    campaign_id: int
    account_id: int
    post_channel_msg_id: int
    comment_text: str
    status: CommentStatus
    posted_message_id: Optional[int] = None
    in_reply_to_message_id: Optional[int] = None
    error: Optional[str] = None


class CommentLogUpdate(BaseModel):
    posted_message_id: Optional[int] = None
    comment_text: Optional[str] = None
    in_reply_to_message_id: Optional[int] = None
    status: Optional[CommentStatus] = None
    error: Optional[str] = None


class CommentLogRead(ORMModel):
    id: int
    campaign_id: int
    account_id: int
    post_channel_msg_id: int
    posted_message_id: Optional[int]
    comment_text: str
    in_reply_to_message_id: Optional[int]
    status: CommentStatus
    error: Optional[str]
    created_at: datetime
