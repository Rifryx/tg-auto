from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from core.enums import CommentStatus
from core.repositories.base import BaseRepository
from modules.commenting.models import CommentLog
from modules.commenting.schemas import CommentLogCreate


class CommentLogRepository(BaseRepository[CommentLog]):
    """Лог комментариев (append-only) с фильтрами и пагинацией."""

    model = CommentLog

    def create(self, data: CommentLogCreate) -> CommentLog:
        record = CommentLog(**data.model_dump())
        return self._add(record)

    def list_by_campaign(
        self,
        campaign_id: int,
        *,
        status: Optional[CommentStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CommentLog]:
        stmt = select(CommentLog).where(CommentLog.campaign_id == campaign_id)
        if status is not None:
            stmt = stmt.where(CommentLog.status == CommentStatus(status).value)
        stmt = (
            stmt.order_by(CommentLog.created_at.desc(), CommentLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_by_account(
        self, account_id: int, *, limit: int = 50, offset: int = 0
    ) -> list[CommentLog]:
        stmt = (
            select(CommentLog)
            .where(CommentLog.account_id == account_id)
            .order_by(CommentLog.created_at.desc(), CommentLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(stmt).scalars().all())
