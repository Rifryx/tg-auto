"""Pydantic-схемы Autopilot API (этап 12)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from core.enums import GoalType


class GoalCreate(BaseModel):
    """Тело POST /autopilot/goals."""

    goal_type: str
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("goal_type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        allowed = {t.value for t in GoalType}
        if v not in allowed:
            raise ValueError(f"goal_type must be one of {sorted(allowed)}")
        return v


class GoalUpdate(BaseModel):
    """Тело PATCH /autopilot/goals/{id}."""

    params: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None


class GoalRead(BaseModel):
    id: int
    user_id: str
    goal_type: str
    params: dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ActionRead(BaseModel):
    id: int
    goal_id: int
    action_type: str
    account_id: Optional[int]
    status: str
    reason: Optional[str]
    meta: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class AutopilotStatus(BaseModel):
    """GET /autopilot/status — снапшот: цели + последние действия."""

    goals: list[GoalRead]
    recent_actions: list[ActionRead]
