from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from core.enums import HealthEventType, TriggeredStatusChange
from core.schemas.base import ORMModel


class HealthEventCreate(BaseModel):
    account_id: int
    event_type: HealthEventType
    meta: Optional[dict[str, Any]] = None
    triggered_status_change: Optional[TriggeredStatusChange] = None


class HealthEventUpdate(BaseModel):
    meta: Optional[dict[str, Any]] = None
    resolved: Optional[bool] = None
    triggered_status_change: Optional[TriggeredStatusChange] = None
    resolved_at: Optional[datetime] = None


class HealthEventRead(ORMModel):
    id: int
    account_id: int
    event_type: HealthEventType
    meta: Optional[dict[str, Any]]
    resolved: bool
    triggered_status_change: Optional[TriggeredStatusChange]
    created_at: datetime
    resolved_at: Optional[datetime]
