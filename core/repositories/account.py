from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select

from core.enums import AccountStatus, WarmingProfile
from core.models import Account
from core.repositories.base import BaseRepository
from core.schemas.account import AccountCreate, AccountUpdate


class AccountRepository(BaseRepository[Account]):
    """Репозиторий аккаунтов.

    Намеренно НЕ содержит никакого способа изменить ``accounts.status`` —
    статус переключает только ``AccountStateMachine`` (инвариант §0.5).
    ``update`` работает лишь по не-статусным полям и защищает иммутабельность
    фингерпринта после стадии ``created`` (инвариант §0.3).
    """

    model = Account

    FINGERPRINT_FIELDS = frozenset(
        {
            "device_model",
            "system_version",
            "app_version",
            "lang_code",
            "system_lang_code",
        }
    )

    def create(self, data: AccountCreate) -> Account:
        # status намеренно не принимается: новый аккаунт всегда `created`
        # (дефолт модели), дальнейшие переходы — только через state machine.
        account = Account(**data.model_dump())
        return self._add(account)

    def update(self, id_: int, data: AccountUpdate) -> Optional[Account]:
        account = self.get(id_)
        if account is None:
            return None

        values = data.model_dump(exclude_unset=True)

        touched_fingerprint = self.FINGERPRINT_FIELDS & values.keys()
        if touched_fingerprint and account.status != AccountStatus.CREATED.value:
            raise ValueError(
                "Фингерпринт неизменяем после стадии 'created' "
                f"(аккаунт в статусе '{account.status}'): "
                f"{sorted(touched_fingerprint)}"
            )

        for field, value in values.items():
            setattr(account, field, value)
        self.session.flush()
        return account

    def list_by_status(self, status: AccountStatus) -> list[Account]:
        stmt = select(Account).where(Account.status == AccountStatus(status).value)
        return list(self.session.execute(stmt).scalars().all())

    def list_filtered(
        self,
        *,
        status: Optional[AccountStatus] = None,
        warming_profile: Optional[WarmingProfile] = None,
        project_id: Optional[int] = None,
        role: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> list[Account]:
        """Один запрос с необязательными фильтрами (этап 2).

        `tag` — фильтр «содержит», работает поверх ARRAY-колонки. `project_id`
        может быть 0, чтобы явно фильтровать «без проекта» (project_id IS NULL)
        — эту логику обрабатываем здесь.
        """
        stmt = select(Account)
        if status is not None:
            stmt = stmt.where(Account.status == AccountStatus(status).value)
        if warming_profile is not None:
            stmt = stmt.where(
                Account.warming_profile == WarmingProfile(warming_profile).value
            )
        if project_id is not None:
            if project_id == 0:
                stmt = stmt.where(Account.project_id.is_(None))
            else:
                stmt = stmt.where(Account.project_id == project_id)
        if role is not None:
            stmt = stmt.where(Account.role == role)
        if tag is not None:
            # ARRAY contains через оператор @>. Быстро благодаря GIN-индексу.
            stmt = stmt.where(Account.tags.contains([tag]))
        return list(self.session.execute(stmt).scalars().all())

    def list_pool_by_profile(self, profile: WarmingProfile) -> list[Account]:
        stmt = select(Account).where(
            Account.status == AccountStatus.POOL.value,
            Account.warming_profile == WarmingProfile(profile).value,
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_by_assigned_container(
        self, container_type: str, container_id: int
    ) -> list[Account]:
        stmt = select(Account).where(
            Account.assigned_container_type == container_type,
            Account.assigned_container_id == container_id,
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_cooldown_expired(self, now: datetime) -> list[Account]:
        stmt = (
            select(Account)
            .where(
                Account.status == AccountStatus.COOLDOWN.value,
                Account.cooldown_until.is_not(None),
                Account.cooldown_until <= now,
            )
            .order_by(Account.cooldown_until)
        )
        return list(self.session.execute(stmt).scalars().all())
