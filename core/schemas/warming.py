from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, model_validator

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
    # Человекочитаемое описание действия (где/что/какая реакция и т.п.).
    detail: Optional[str] = None
    created_at: datetime

    @model_validator(mode="after")
    def _fill_detail(self) -> "WarmingActivityRead":
        if self.detail is None:
            from core.warming_detail import warming_detail

            self.detail = warming_detail(
                self.action_type.value
                if hasattr(self.action_type, "value")
                else str(self.action_type),
                target=self.target,
                meta=self.meta,
                status=(
                    self.status.value
                    if hasattr(self.status, "value")
                    else str(self.status)
                ),
            )
        return self
