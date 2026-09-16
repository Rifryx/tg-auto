from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from core.enums import BulkActionType, BulkItemStatus, BulkJobStatus
from core.schemas.base import ORMModel


class BulkJobCreate(BaseModel):
    """Тело запроса на создание bulk-задания."""

    model_config = ConfigDict(extra="forbid")

    action_type: BulkActionType
    account_ids: list[int]
    payload: dict[str, Any] = {}


class BulkJobRead(ORMModel):
    id: int
    action_type: BulkActionType
    payload: dict[str, Any]
    initiator: str
    status: BulkJobStatus
    total_count: int
    done_count: int
    failed_count: int
    skipped_count: int
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class BulkJobItemRead(ORMModel):
    id: int
    job_id: int
    account_id: int
    status: BulkItemStatus
    error: Optional[str]
    result: Optional[dict[str, Any]]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class BulkJobDetail(BaseModel):
    """Полный вид: заголовок + все элементы."""

    job: BulkJobRead
    items: list[BulkJobItemRead]
