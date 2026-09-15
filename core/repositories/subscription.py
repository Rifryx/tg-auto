"""Репозиторий подписок пользователей Mini App."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.subscription import Subscription


class SubscriptionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: str) -> Optional[Subscription]:
        return self.session.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        ).scalar_one_or_none()

    def upsert(
        self,
        user_id: str,
        plan_id: str,
        payment_method: Optional[str] = None,
    ) -> Subscription:
        existing = self.get(user_id)
        if existing is None:
            existing = Subscription(
                user_id=user_id,
                plan_id=plan_id,
                payment_method=payment_method,
            )
            self.session.add(existing)
        else:
            existing.plan_id = plan_id
            if payment_method is not None:
                existing.payment_method = payment_method
        self.session.flush()
        return existing
