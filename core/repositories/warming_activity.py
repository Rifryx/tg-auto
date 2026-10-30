from __future__ import annotations

from sqlalchemy import delete, select

from core.models import WarmingActivity
from core.repositories.base import BaseRepository
from core.schemas.warming import WarmingActivityCreate

# Сколько последних записей ленты прогрева держим на аккаунт. Лента append-only
# и пухнет бесконечно («был онлайн» каждые несколько минут) — и БД, и выдача
# растут без границы. Держим только хвост: для диагностики свежего достаточно.
DEFAULT_KEEP = 150


class WarmingActivityRepository(BaseRepository[WarmingActivity]):
    """Лента действий прогрева. По сути append-only (§5.1), но с обрезкой хвоста."""

    model = WarmingActivity

    def create(self, data: WarmingActivityCreate) -> WarmingActivity:
        activity = WarmingActivity(**data.model_dump())
        return self._add(activity)

    def trim_account(self, account_id: int, keep: int = DEFAULT_KEEP) -> int:
        """Удаляет всё, кроме ``keep`` самых свежих записей аккаунта.

        Вызывается после вставки нового тика прогрева, чтобы лента не росла
        бесконечно. Возвращает число удалённых строк. ``keep <= 0`` трактуем как
        «ничего не удалять» (защита от случайной полной очистки)."""
        if keep <= 0:
            return 0
        stale = (
            select(WarmingActivity.id)
            .where(WarmingActivity.account_id == account_id)
            .order_by(WarmingActivity.created_at.desc(), WarmingActivity.id.desc())
            .offset(keep)
        )
        ids = list(self.session.execute(stale).scalars().all())
        if not ids:
            return 0
        self.session.execute(
            delete(WarmingActivity).where(WarmingActivity.id.in_(ids))
        )
        return len(ids)

    def list_by_account(self, account_id: int, limit: int = 100) -> list[WarmingActivity]:
        stmt = (
            select(WarmingActivity)
            .where(WarmingActivity.account_id == account_id)
            .order_by(WarmingActivity.created_at.desc(), WarmingActivity.id.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())
