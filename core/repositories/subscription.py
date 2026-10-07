"""Репозиторий подписок пользователей Mini App."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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

    def extend_pro(self, user_id: str, period_days: int, payment_method: str) -> None:
        """Атомарно продлить Pro на ``period_days`` дней.

        Критично для корректности: продление считается ОДНИМ SQL-оператором
        (``INSERT … ON CONFLICT DO UPDATE``), без read-modify-write на стороне
        Python. Два одновременных платежа одного пользователя не затрут друг
        друга — каждый честно добавит свой период поверх актуального значения.

        Правило стекания:
            expires_at = GREATEST(COALESCE(expires_at, now()), now()) + period

        То есть: если подписка ещё активна — период добавляется к концу; если
        истекла или её не было — отсчёт идёт от ``now()``.
        """
        interval = func.make_interval(0, 0, 0, period_days)  # days-аргумент
        new_expires = func.greatest(
            func.coalesce(Subscription.expires_at, func.now()), func.now()
        ) + interval
        stmt = pg_insert(Subscription).values(
            user_id=user_id,
            plan_id="pro",
            payment_method=payment_method,
            expires_at=func.now() + interval,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Subscription.user_id],
            set_={
                "plan_id": "pro",
                "payment_method": payment_method,
                "expires_at": new_expires,
            },
        )
        self.session.execute(stmt)
