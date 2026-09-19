"""Репозитории Autopilot (этап 12)."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select

from core.models.autopilot import AutopilotAction, AutopilotGoal
from core.repositories.base import BaseRepository


class AutopilotGoalRepository(BaseRepository[AutopilotGoal]):
    model = AutopilotGoal

    def create(
        self, *, user_id: str, goal_type: str, params: dict[str, Any]
    ) -> AutopilotGoal:
        obj = AutopilotGoal(
            user_id=user_id,
            goal_type=goal_type,
            params=params,
            enabled=True,
        )
        return self._add(obj)

    def list_for_user(self, user_id: str) -> list[AutopilotGoal]:
        stmt = (
            select(AutopilotGoal)
            .where(AutopilotGoal.user_id == user_id)
            .order_by(AutopilotGoal.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_enabled(self) -> list[AutopilotGoal]:
        stmt = select(AutopilotGoal).where(AutopilotGoal.enabled.is_(True))
        return list(self.session.execute(stmt).scalars().all())

    def update(
        self,
        goal_id: int,
        *,
        params: Optional[dict[str, Any]] = None,
        enabled: Optional[bool] = None,
    ) -> Optional[AutopilotGoal]:
        obj = self.get(goal_id)
        if obj is None:
            return None
        if params is not None:
            obj.params = params
        if enabled is not None:
            obj.enabled = enabled
        self.session.flush()
        return obj

    def delete(self, goal_id: int) -> bool:
        obj = self.get(goal_id)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True


class AutopilotActionRepository(BaseRepository[AutopilotAction]):
    model = AutopilotAction

    def log(
        self,
        *,
        goal_id: int,
        action_type: str,
        account_id: Optional[int],
        status: str,
        reason: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> AutopilotAction:
        obj = AutopilotAction(
            goal_id=goal_id,
            action_type=action_type,
            account_id=account_id,
            status=status,
            reason=reason,
            meta=meta or {},
        )
        return self._add(obj)

    def list_recent_for_user(
        self, user_id: str, limit: int = 20
    ) -> list[AutopilotAction]:
        """Последние N действий по всем целям пользователя."""
        stmt = (
            select(AutopilotAction)
            .join(AutopilotGoal, AutopilotAction.goal_id == AutopilotGoal.id)
            .where(AutopilotGoal.user_id == user_id)
            .order_by(AutopilotAction.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())
