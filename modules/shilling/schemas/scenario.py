"""Pydantic-схемы сценария, ролей и шагов.

См. docs/neuroshilling-spec.md § 3.2–3.4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.schemas.base import ORMModel

StepType = Literal["message", "reaction"]


# --- сценарий -----------------------------------------------------------------


class ScenarioCreate(BaseModel):
    # NULL допустим — для шаблонов, ещё не привязанных к кампании.
    campaign_id: Optional[int] = None
    name: Optional[str] = Field(default=None, min_length=1)
    is_template: bool = False
    persons_count: int = Field(default=2, ge=2)
    ai_generated: bool = False


class ScenarioUpdate(BaseModel):
    campaign_id: Optional[int] = None
    name: Optional[str] = Field(default=None, min_length=1)
    is_template: Optional[bool] = None
    persons_count: Optional[int] = Field(default=None, ge=2)
    ai_generated: Optional[bool] = None


class ScenarioRead(ORMModel):
    id: int
    campaign_id: Optional[int]
    name: Optional[str]
    is_template: bool
    persons_count: int
    ai_generated: bool
    created_at: datetime
    updated_at: datetime


# --- роль --------------------------------------------------------------------


class RoleCreate(BaseModel):
    scenario_id: Optional[int] = None  # игнорируется репозиторием (берётся из URL)
    name: str = Field(min_length=1)
    character: Optional[str] = None
    color: Optional[str] = None
    sort_order: int = 0


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    character: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


class RoleRead(ORMModel):
    id: int
    scenario_id: int
    name: str
    character: Optional[str]
    color: Optional[str]
    sort_order: int


# --- шаг ---------------------------------------------------------------------


class StepCreate(BaseModel):
    scenario_id: Optional[int] = None  # берётся из URL
    role_id: int
    step_order: Optional[int] = None  # авто (next_order), если не задан
    step_type: StepType = "message"
    text: Optional[str] = None
    reply_to_step_id: Optional[int] = None
    delay_before_sec: Optional[int] = Field(default=None, ge=0)
    reaction_emoji: Optional[str] = None

    def model_post_init(self, __context) -> None:
        # Валидируем согласованность payload↔тип на уровне API до записи в БД
        # (в БД тот же CheckConstraint страхует).
        if self.step_type == "message" and not (self.text and self.text.strip()):
            raise ValueError("step_type='message' requires non-empty text")
        if self.step_type == "reaction" and not (self.reaction_emoji and self.reaction_emoji.strip()):
            raise ValueError("step_type='reaction' requires reaction_emoji")


class StepUpdate(BaseModel):
    role_id: Optional[int] = None
    step_order: Optional[int] = None
    step_type: Optional[StepType] = None
    text: Optional[str] = None
    reply_to_step_id: Optional[int] = None
    delay_before_sec: Optional[int] = Field(default=None, ge=0)
    reaction_emoji: Optional[str] = None


class StepRead(ORMModel):
    id: int
    scenario_id: int
    role_id: int
    step_order: int
    step_type: StepType
    text: Optional[str]
    reply_to_step_id: Optional[int]
    delay_before_sec: Optional[int]
    reaction_emoji: Optional[str]


class StepReorderRequest(BaseModel):
    step_ids: list[int] = Field(min_length=1)


# --- ИИ-генерация сценария ---------------------------------------------------


class GenerateRoleInput(BaseModel):
    """Опциональная роль на входе генерации (если роли задаёт пользователь)."""

    name: str = Field(min_length=1)
    character: str = ""


class ScenarioGenerateRequest(BaseModel):
    topic: str = Field(min_length=1)
    brand_name: Optional[str] = None  # если None — берётся из кампании
    persons_count: int = Field(default=2, ge=2, le=10)
    steps_count: Optional[int] = Field(default=None, ge=2, le=30)
    roles: Optional[list[GenerateRoleInput]] = None


class GeneratedRoleRead(BaseModel):
    name: str
    character: str = ""


class GeneratedStepRead(BaseModel):
    role: str
    text: str
    reply_to_step: Optional[int] = None


class GeneratedScenarioRead(BaseModel):
    """Черновик сценария от ИИ — фронт решает, применять ли через PUT."""

    roles: list[GeneratedRoleRead]
    steps: list[GeneratedStepRead]
