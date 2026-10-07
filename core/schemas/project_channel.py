"""Read-схема канала, созданного аккаунтом (этап 8/«Управление аккаунтом»).

Источник правды — ``project_channels`` (пишется bulk-action ``create_channel``).
Эндпоинт ``GET /accounts/{id}/project-channels`` отдаёт этот список для карточки
аккаунта: UI показывает созданные каналы и даёт управлять их постами.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from core.schemas.base import ORMModel


class ProjectChannelRead(ORMModel):
    id: int
    account_id: int
    project_id: Optional[int]
    channel_tg_id: int
    channel_access_hash: Optional[int]
    title: str
    username: Optional[str]
    is_megagroup: bool
    pinned_message_id: Optional[int]
    created_at: datetime
