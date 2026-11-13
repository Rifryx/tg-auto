"""Репозиторий append-only лога реакций."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select

from core.repositories.base import BaseRepository
from modules.mass_reactions.models import MassReactionLog


class LogRepository(BaseRepository[MassReactionLog]):
    model = MassReactionLog

    def append(
        self,
        *,
        campaign_id: int,
        account_id: int,
        chat_id: int,
        outcome: str,
        started_at: datetime,
        finished_at: datetime,
        message_tg_id: Optional[int] = None,
        emoji: Optional[str] = None,
        error_code: Optional[str] = None,
        flood_wait_sec: Optional[int] = None,
        latency_ms: int = 0,
        dry_run: bool = False,
    ) -> MassReactionLog:
        return self._add(
            MassReactionLog(
                campaign_id=campaign_id,
                account_id=account_id,
                chat_id=chat_id,
                outcome=outcome,
                started_at=started_at,
                finished_at=finished_at,
                message_tg_id=message_tg_id,
                emoji=emoji,
                error_code=error_code,
                flood_wait_sec=flood_wait_sec,
                latency_ms=latency_ms,
                dry_run=dry_run,
            )
        )

    def count_by_outcome(self, campaign_id: int) -> dict[str, int]:
        stmt = (
            select(MassReactionLog.outcome, func.count())
            .where(MassReactionLog.campaign_id == campaign_id)
            .group_by(MassReactionLog.outcome)
        )
        return {str(o): int(c) for o, c in self.session.execute(stmt).all()}
