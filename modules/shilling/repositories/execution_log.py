"""Репозиторий лога выполнения (append-only)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import func, select

from core.repositories.base import BaseRepository
from modules.shilling.models import ShillingExecutionLog

if TYPE_CHECKING:  # pragma: no cover
    from modules.shilling.schemas.execution_log import ExecutionLogCreate


class ExecutionLogRepository(BaseRepository[ShillingExecutionLog]):
    """Лог append-only: методов update/delete намеренно нет — история
    выполнения не переписывается. Удаление возможно только каскадом при
    удалении кампании (CASCADE в БД)."""

    model = ShillingExecutionLog

    def create(self, data: "ExecutionLogCreate") -> ShillingExecutionLog:
        record = ShillingExecutionLog(**data.model_dump(exclude_unset=True))
        return self._add(record)

    def list_by_campaign(
        self,
        campaign_id: int,
        *,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ShillingExecutionLog]:
        stmt = select(ShillingExecutionLog).where(
            ShillingExecutionLog.campaign_id == campaign_id
        )
        if status is not None:
            stmt = stmt.where(ShillingExecutionLog.status == status)
        stmt = (
            stmt.order_by(
                ShillingExecutionLog.created_at.desc(),
                ShillingExecutionLog.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(stmt).scalars())

    def list_by_account(
        self, account_id: int, *, limit: int = 50, offset: int = 0
    ) -> list[ShillingExecutionLog]:
        stmt = (
            select(ShillingExecutionLog)
            .where(ShillingExecutionLog.account_id == account_id)
            .order_by(
                ShillingExecutionLog.created_at.desc(),
                ShillingExecutionLog.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(stmt).scalars())

    def count_by_status(self, campaign_id: int) -> dict[str, int]:
        """Агрегат для CampaignStats: {'sent': N, 'failed': M, ...}."""
        stmt = (
            select(ShillingExecutionLog.status, func.count())
            .where(ShillingExecutionLog.campaign_id == campaign_id)
            .group_by(ShillingExecutionLog.status)
        )
        result: dict[str, int] = {"sent": 0, "failed": 0, "skipped": 0, "replaced": 0}
        for status, count in self.session.execute(stmt).all():
            result[status] = count
        return result

    def list_failed_for_target(
        self, campaign_id: int, target_id: int
    ) -> list[ShillingExecutionLog]:
        """Failed-логи для конкретной цели — failover не пробует их повторно
        теми же аккаунтами."""
        stmt = select(ShillingExecutionLog).where(
            ShillingExecutionLog.campaign_id == campaign_id,
            ShillingExecutionLog.target_id == target_id,
            ShillingExecutionLog.status == "failed",
        )
        return list(self.session.execute(stmt).scalars())
