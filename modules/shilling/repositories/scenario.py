"""Репозитории сценариев, ролей, шагов диалога."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.shilling.models import (
    ShillingScenario,
    ShillingScenarioRole,
    ShillingScenarioStep,
)

if TYPE_CHECKING:  # pragma: no cover
    from modules.shilling.schemas.scenario import (
        RoleCreate,
        RoleUpdate,
        ScenarioCreate,
        ScenarioUpdate,
        StepCreate,
        StepUpdate,
    )


# --- сценарий -----------------------------------------------------------------


class ScenarioRepository(BaseRepository[ShillingScenario]):
    model = ShillingScenario

    def get_by_campaign(self, campaign_id: int) -> Optional[ShillingScenario]:
        stmt = select(ShillingScenario).where(ShillingScenario.campaign_id == campaign_id)
        return self.session.execute(stmt).scalars().first()

    def list_templates(self) -> list[ShillingScenario]:
        stmt = (
            select(ShillingScenario)
            .where(ShillingScenario.is_template.is_(True))
            .order_by(ShillingScenario.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def create(self, data: "ScenarioCreate") -> ShillingScenario:
        return self._add(ShillingScenario(**data.model_dump(exclude_unset=True)))

    def update(self, id_: int, data: "ScenarioUpdate") -> Optional[ShillingScenario]:
        obj = self.get(id_)
        if obj is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        self.session.flush()
        return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True


# --- роль --------------------------------------------------------------------


class ScenarioRoleRepository(BaseRepository[ShillingScenarioRole]):
    model = ShillingScenarioRole

    def list_by_scenario(self, scenario_id: int) -> list[ShillingScenarioRole]:
        stmt = (
            select(ShillingScenarioRole)
            .where(ShillingScenarioRole.scenario_id == scenario_id)
            .order_by(ShillingScenarioRole.sort_order.asc(), ShillingScenarioRole.id.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def create(self, scenario_id: int, data: "RoleCreate") -> ShillingScenarioRole:
        payload = data.model_dump(exclude_unset=True)
        payload.pop("scenario_id", None)  # scenario_id всегда из аргумента
        return self._add(ShillingScenarioRole(scenario_id=scenario_id, **payload))

    def update(self, id_: int, data: "RoleUpdate") -> Optional[ShillingScenarioRole]:
        obj = self.get(id_)
        if obj is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        self.session.flush()
        return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True


# --- шаг ---------------------------------------------------------------------


class ScenarioStepRepository(BaseRepository[ShillingScenarioStep]):
    model = ShillingScenarioStep

    def list_by_scenario(self, scenario_id: int) -> list[ShillingScenarioStep]:
        stmt = (
            select(ShillingScenarioStep)
            .where(ShillingScenarioStep.scenario_id == scenario_id)
            .order_by(ShillingScenarioStep.step_order.asc(), ShillingScenarioStep.id.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def list_by_role(self, role_id: int) -> list[ShillingScenarioStep]:
        stmt = (
            select(ShillingScenarioStep)
            .where(ShillingScenarioStep.role_id == role_id)
            .order_by(ShillingScenarioStep.step_order.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def next_order(self, scenario_id: int) -> int:
        """Следующий свободный step_order для сценария (для POST /steps)."""
        stmt = select(ShillingScenarioStep.step_order).where(
            ShillingScenarioStep.scenario_id == scenario_id
        )
        used = [row for row in self.session.execute(stmt).scalars()]
        return (max(used) + 1) if used else 1

    def create(self, scenario_id: int, data: "StepCreate") -> ShillingScenarioStep:
        payload = data.model_dump(exclude_unset=True)
        payload.pop("scenario_id", None)
        if "step_order" not in payload:
            payload["step_order"] = self.next_order(scenario_id)
        return self._add(ShillingScenarioStep(scenario_id=scenario_id, **payload))

    def update(self, id_: int, data: "StepUpdate") -> Optional[ShillingScenarioStep]:
        obj = self.get(id_)
        if obj is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        self.session.flush()
        return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True

    def reorder(self, scenario_id: int, step_ids_in_order: list[int]) -> bool:
        """Атомарно переставляет step_order для перечисленных шагов сценария.

        Возвращает False, если какой-то из id не принадлежит сценарию, — тогда
        ни один шаг не изменён (вызывающий должен откатить транзакцию).
        Порядок нумеруется с 1.
        """
        steps = {s.id: s for s in self.list_by_scenario(scenario_id)}
        if any(sid not in steps for sid in step_ids_in_order):
            return False
        for new_order, sid in enumerate(step_ids_in_order, start=1):
            steps[sid].step_order = new_order
        self.session.flush()
        return True
