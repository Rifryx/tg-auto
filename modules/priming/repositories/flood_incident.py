"""Репозиторий FLOOD_WAIT-инцидентов."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.priming.models import PrimingFloodIncident


class FloodIncidentRepository(BaseRepository[PrimingFloodIncident]):
    model = PrimingFloodIncident

    def get_by_id(self, id_: int) -> Optional[PrimingFloodIncident]:
        return self.get(id_)

    def list_by_campaign_account(
        self,
        campaign_account_id: int,
        *,
        limit: int = 50,
    ) -> list[PrimingFloodIncident]:
        stmt = (
            select(PrimingFloodIncident)
            .where(
                PrimingFloodIncident.campaign_account_id
                == campaign_account_id
            )
            .order_by(PrimingFloodIncident.id.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def append(
        self,
        *,
        campaign_account_id: int,
        flood_wait_sec: int,
        endpoint: str,
        at: Optional[datetime] = None,
    ) -> PrimingFloodIncident:
        obj = PrimingFloodIncident(
            campaign_account_id=campaign_account_id,
            flood_wait_sec=flood_wait_sec,
            endpoint=endpoint,
        )
        if at is not None:
            obj.at = at
        return self._add(obj)

    def delete_hard(self, id_: int) -> bool:
        obj = self.get(id_)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True
