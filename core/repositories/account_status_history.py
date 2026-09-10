from __future__ import annotations

from sqlalchemy import select

from core.models import AccountStatusHistory
from core.repositories.base import BaseRepository
from core.schemas.history import AccountStatusHistoryCreate


class AccountStatusHistoryRepository(BaseRepository[AccountStatusHistory]):
    """Аудит-лог переходов стадий. Append-only: записи не меняются и не удаляются.

    Пишется в рамках транзакции state machine; изменение самого ``accounts.status``
    здесь не происходит — только фиксация факта перехода.
    """

    model = AccountStatusHistory

    def create(self, data: AccountStatusHistoryCreate) -> AccountStatusHistory:
        record = AccountStatusHistory(**data.model_dump())
        return self._add(record)

    def list_by_account(
        self, account_id: int, limit: int = 100
    ) -> list[AccountStatusHistory]:
        stmt = (
            select(AccountStatusHistory)
            .where(AccountStatusHistory.account_id == account_id)
            .order_by(AccountStatusHistory.created_at.desc(), AccountStatusHistory.id.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())
