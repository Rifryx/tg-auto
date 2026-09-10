from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from core.enums import WarmingActionType, WarmingActivityKind, WarmingActivityStatus
from core.schemas.base import ORMModel


class WarmingActivityCreate(BaseModel):
    account_id: int
    kind: WarmingActivityKind
    action_type: WarmingActionType
    status: WarmingActivityStatus
    target: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


class WarmingActivityUpdate(BaseModel):
    kind: Optional[WarmingActivityKind] = None
    action_type: Optional[WarmingActionType] = None
    status: Optional[WarmingActivityStatus] = None
    target: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


class WarmingActivityRead(ORMModel):
    id: int
    account_id: int
    kind: WarmingActivityKind
    action_type: WarmingActionType
    target: Optional[str]
    status: WarmingActivityStatus
    meta: Optional[dict[str, Any]]
    created_at: datetime
