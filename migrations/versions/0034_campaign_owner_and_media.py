"""Владелец кампании + привязка медиа-ассетов к кампании (E4.1).

* ``campaigns.owner_user_id`` — Telegram id владельца (VARCHAR, nullable для
  совместимости со старыми кампаниями). Нужен, чтобы:
  * выбирать медиа-ассеты только этого пользователя для attach_image;
  * позже — фильтр «мои кампании» на дашборде.
* ``commenting.campaign_media_assets`` — какие картинки к кампании: пользователь
  явно приложил через UI. При удалении кампании — CASCADE; при удалении
  ассета — CASCADE (не хотим полу-удалённых ссылок).

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("owner_user_id", sa.String(), nullable=True),
        schema="commenting",
    )
    op.create_index(
        "ix_campaigns_owner_user_id",
        "campaigns",
        ["owner_user_id"],
        schema="commenting",
    )

    op.create_table(
        "campaign_media_assets",
        sa.Column(
            "campaign_id",
            sa.BigInteger(),
            sa.ForeignKey("commenting.campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "media_asset_id",
            sa.BigInteger(),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "campaign_id", "media_asset_id", name="pk_campaign_media_assets"
        ),
        schema="commenting",
    )
    op.create_index(
        "ix_campaign_media_assets_campaign_id",
        "campaign_media_assets",
        ["campaign_id"],
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_campaign_media_assets_campaign_id",
        table_name="campaign_media_assets",
        schema="commenting",
    )
    op.drop_table("campaign_media_assets", schema="commenting")
    op.drop_index(
        "ix_campaigns_owner_user_id",
        table_name="campaigns",
        schema="commenting",
    )
    op.drop_column("campaigns", "owner_user_id", schema="commenting")
