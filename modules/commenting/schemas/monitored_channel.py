from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from core.schemas.base import ORMModel


class MonitoredChannelRead(ORMModel):
    id: int
    account_id: int
    input_ref: str
    is_folder: bool
    channel_ref: Optional[str]
    channel_tg_id: Optional[int]
    title: Optional[str]
    discussion_group_id: Optional[int]
    status: str
    subscribed: bool
    error: Optional[str]
    created_at: datetime
    updated_at: datetime


class AddChannelsRequest(BaseModel):
    # Ссылки/юзернеймы каналов ИЛИ ссылки на папки (addlist) при is_folder=true.
    refs: list[str]
    is_folder: bool = False
