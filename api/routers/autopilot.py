"""API-эндпоинты Autopilot (этап 12).

CRUD целей + чтение снимка (цели + последние действия). Действия применяет
worker (``autopilot.tick`` cron), API их только показывает.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from core.repositories.autopilot import (
    AutopilotActionRepository,
    AutopilotGoalRepository,
)
from core.schemas.autopilot import (
    ActionRead,
    AutopilotStatus,
    GoalCreate,
    GoalRead,
    GoalUpdate,
)

router = APIRouter(
    prefix="/autopilot", tags=["autopilot"], dependencies=[Depends(require_user)]
)


@router.get("/goals", response_model=list[GoalRead])
def list_goals(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    return AutopilotGoalRepository(session).list_for_user(user_id)


@router.post("/goals", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
def create_goal(
    body: GoalCreate,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    goal = AutopilotGoalRepository(session).create(
        user_id=user_id, goal_type=body.goal_type, params=body.params
    )
    session.commit()
    return goal


@router.patch("/goals/{goal_id}", response_model=GoalRead)
def update_goal(
    goal_id: int,
    body: GoalUpdate,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    repo = AutopilotGoalRepository(session)
    goal = repo.get(goal_id)
    if goal is None or goal.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "goal not found")
    updated = repo.update(goal_id, params=body.params, enabled=body.enabled)
    session.commit()
    return updated


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(
    goal_id: int,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    repo = AutopilotGoalRepository(session)
    goal = repo.get(goal_id)
    if goal is None or goal.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "goal not found")
    repo.delete(goal_id)
    session.commit()
    return None


@router.get("/status", response_model=AutopilotStatus)
def get_status(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    goals = AutopilotGoalRepository(session).list_for_user(user_id)
    actions = AutopilotActionRepository(session).list_recent_for_user(user_id, limit=20)
    return AutopilotStatus(
        goals=[GoalRead.model_validate(g) for g in goals],
        recent_actions=[ActionRead.model_validate(a) for a in actions],
    )
