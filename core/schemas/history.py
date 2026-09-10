from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from core.enums import AccountStatus, Initiator
from core.schemas.base import ORMModel


class AccountStatusHistoryCreate(BaseModel):
    account_id: int
    to_status: AccountStatus
    reason: str
    initiator: Initiator
    from_status: Optional[AccountStatus] = None
    meta: Optional[dict[str, Any]] = None


class AccountStatusHistoryRead(ORMModel):
    id: int
    account_id: int
    from_status: Optional[AccountStatus]
    to_status: AccountStatus
    reason: str
    initiator: Initiator
    meta: Optional[dict[str, Any]]
    created_at: datetime
