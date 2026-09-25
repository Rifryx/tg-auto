"""Репозиторий привязок аккаунтов к кампании шиллинга."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import and_, select

from core.repositories.base import BaseRepository
from modules.shilling.models import ShillingCampaignAccount

if TYPE_CHECKING:  # pragma: no cover
    from modules.shilling.schemas.campaign_account import (
        CampaignAccountUpdate,
    )


class CampaignAccountRepository(BaseRepository[ShillingCampaignAccount]):
    """Аккаунт может участвовать в разных кампаниях (не эксклюзивно).

    Уникальность обеспечивается только парой (campaign_id, account_id) —
    см. ORM-модель.
    """

    model = ShillingCampaignAccount

    def get_link(
        self, campaign_id: int, account_id: int
    ) -> Optional[ShillingCampaignAccount]:
        stmt = select(ShillingCampaignAccount).where(
            and_(
                ShillingCampaignAccount.campaign_id == campaign_id,
                ShillingCampaignAccount.account_id == account_id,
            )
        )
        return self.session.execute(stmt).scalars().first()

    def list_by_campaign(self, campaign_id: int) -> list[ShillingCampaignAccount]:
        stmt = (
            select(ShillingCampaignAccount)
            .where(ShillingCampaignAccount.campaign_id == campaign_id)
            .order_by(
                ShillingCampaignAccount.is_reserve.asc(),
                ShillingCampaignAccount.created_at.asc(),
            )
        )
        return list(self.session.execute(stmt).scalars())

    def list_by_role(self, role_id: int) -> list[ShillingCampaignAccount]:
        stmt = select(ShillingCampaignAccount).where(
            ShillingCampaignAccount.role_id == role_id
        )
        return list(self.session.execute(stmt).scalars())

    def list_reserve(self, campaign_id: int) -> list[ShillingCampaignAccount]:
        stmt = select(ShillingCampaignAccount).where(
            and_(
                ShillingCampaignAccount.campaign_id == campaign_id,
                ShillingCampaignAccount.is_reserve.is_(True),
            )
        )
        return list(self.session.execute(stmt).scalars())

    def list_primary_by_role(
        self, campaign_id: int, role_id: int
    ) -> list[ShillingCampaignAccount]:
        """Основные (не резервные) аккаунты роли — для orchestrator/executor."""
        stmt = select(ShillingCampaignAccount).where(
            and_(
                ShillingCampaignAccount.campaign_id == campaign_id,
                ShillingCampaignAccount.role_id == role_id,
                ShillingCampaignAccount.is_reserve.is_(False),
            )
        )
        return list(self.session.execute(stmt).scalars())

    def attach(
        self,
        campaign_id: int,
        account_id: int,
        *,
        role_id: Optional[int] = None,
        is_reserve: bool = False,
    ) -> ShillingCampaignAccount:
        """Привязывает аккаунт к кампании. UNIQUE-констрейнт спасает от дублей."""
        link = ShillingCampaignAccount(
            campaign_id=campaign_id,
            account_id=account_id,
            role_id=role_id,
            is_reserve=is_reserve,
        )
        return self._add(link)

    def detach(self, campaign_id: int, account_id: int) -> bool:
        link = self.get_link(campaign_id, account_id)
        if link is None:
            return False
        self.session.delete(link)
        self.session.flush()
        return True

    def reassign_role(
        self, campaign_id: int, account_id: int, role_id: Optional[int]
    ) -> Optional[ShillingCampaignAccount]:
        link = self.get_link(campaign_id, account_id)
        if link is None:
            return None
        link.role_id = role_id
        self.session.flush()
        return link

    def update(
        self,
        campaign_id: int,
        account_id: int,
        data: "CampaignAccountUpdate",
    ) -> Optional[ShillingCampaignAccount]:
        link = self.get_link(campaign_id, account_id)
        if link is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(link, field, value)
        self.session.flush()
        return link
