from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from core.enums import CommentStatus
from core.schemas.base import ORMModel


class CommentLogCreate(BaseModel):
    campaign_id: int
    account_id: int
    post_channel_msg_id: int
    comment_text: str
    status: CommentStatus
    posted_message_id: Optional[int] = None
    in_reply_to_message_id: Optional[int] = None
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
