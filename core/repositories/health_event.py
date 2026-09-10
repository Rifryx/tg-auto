from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from core.models import HealthEvent
from core.repositories.base import BaseRepository
from core.schemas.health import HealthEventCreate, HealthEventUpdate


class HealthEventRepository(BaseRepository[HealthEvent]):
    model = HealthEvent

    def create(self, data: HealthEventCreate) -> HealthEvent:
        event = HealthEvent(**data.model_dump())
        return self._add(event)

    def update(self, id_: int, data: HealthEventUpdate) -> Optional[HealthEvent]:
        event = self.get(id_)
        if event is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(event, field, value)
        self.session.flush()
        return event

    def list_by_account(self, account_id: int, limit: int = 100) -> list[HealthEvent]:
        stmt = (
            select(HealthEvent)
            .where(HealthEvent.account_id == account_id)
            .order_by(HealthEvent.created_at.desc(), HealthEvent.id.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_unresolved(self) -> list[HealthEvent]:
        stmt = (
            select(HealthEvent)
            .where(HealthEvent.resolved.is_(False))
            .order_by(HealthEvent.created_at.desc(), HealthEvent.id.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def resolve(self, id_: int, resolved_at: Optional[datetime] = None) -> Optional[HealthEvent]:
        event = self.get(id_)
        if event is None:
            return None
        event.resolved = True
        event.resolved_at = resolved_at or datetime.now(timezone.utc)
        self.session.flush()
        return event
