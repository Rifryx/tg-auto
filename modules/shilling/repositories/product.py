"""Репозиторий продуктов нейрошиллинга (база знаний для LLM-контекста).

Все запросы — в рамках owner_user_id (мульти-тенант по владельцу продукта).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.shilling.models import ShillingProduct


class ProductRepository(BaseRepository[ShillingProduct]):
    model = ShillingProduct

    def list_by_owner(self, owner_user_id: str) -> list[ShillingProduct]:
        stmt = (
            select(ShillingProduct)
            .where(ShillingProduct.owner_user_id == owner_user_id)
            .order_by(ShillingProduct.updated_at.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def get_owned(
        self, product_id: int, owner_user_id: str
    ) -> Optional[ShillingProduct]:
        """Строго в контексте владельца — чужой продукт достать нельзя."""
        stmt = select(ShillingProduct).where(
            ShillingProduct.id == product_id,
            ShillingProduct.owner_user_id == owner_user_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()
