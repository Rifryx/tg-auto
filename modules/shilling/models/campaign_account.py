"""Привязка аккаунта к кампании шиллинга + назначенная роль/резерв.

В отличие от commenting.CampaignAccount (эксклюзивная привязка), тут
аккаунт МОЖЕТ участвовать в разных кампаниях шиллинга — эксклюзивна
только пара (campaign_id, account_id).

См. docs/neuroshilling-spec.md § 3.5.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import SHILLING_SCHEMA, Base, CreatedAtMixin


class ShillingCampaignAccount(Base, CreatedAtMixin):
    __tablename__ = "campaign_accounts"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "account_id",
            name="uq_campaign_accounts_campaign_id_account_id",
        ),
        {"schema": SHILLING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Роль в текущем сценарии кампании. NULL — аккаунт добавлен, но роль
    # ещё не назначена (например, пришёл через drag-and-drop в «резерв»).
    # SET NULL при удалении роли: аккаунт останется в пуле кампании.
    role_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.scenario_roles.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_reserve: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
