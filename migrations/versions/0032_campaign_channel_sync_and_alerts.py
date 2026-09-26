"""Синхронизация целевых каналов кампании + алерты каналов (E3.2).

* ``monitored_channels.source_campaign_id`` — строка мониторинга создана
  синхронизацией кампании (а не вручную на аккаунте). По нему при удалении
  ссылки из кампании / отвязке аккаунта снимаются ровно «кампанийные» строки,
  а ручные каналы аккаунта не трогаются. SET NULL при удалении кампании.
* ``commenting.channel_alerts`` — события по каналам для уведомлений:
  ``not_subscribed`` (аккаунт не подписан, политика «только уведомить»),
  ``auto_subscribed`` (подписали сами), ``access_lost`` (ошибка доступа при
  отправке), ``blacklisted`` (канал ушёл в ЧС автоматически). Отдельно от
  health_events: те влияют на риск бана, а неподписка — не сигнал бана.

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KINDS = "'not_subscribed', 'auto_subscribed', 'access_lost', 'blacklisted'"


def upgrade() -> None:
    op.add_column(
        "monitored_channels",
        sa.Column(
            "source_campaign_id",
            sa.BigInteger(),
            sa.ForeignKey("commenting.campaigns.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema="commenting",
    )
    op.create_index(
        "ix_monitored_channels_source_campaign_id",
        "monitored_channels",
        ["source_campaign_id"],
        schema="commenting",
    )

    op.create_table(
        "channel_alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.BigInteger(),
            sa.ForeignKey("commenting.campaigns.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "account_id",
            sa.BigInteger(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel_ref", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=True),
        sa.Column(
            "resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"kind IN ({_KINDS})", name="channel_alert_kind_allowed"),
        schema="commenting",
    )
    op.create_index(
        "ix_channel_alerts_open",
        "channel_alerts",
        ["resolved", sa.text("created_at DESC")],
        schema="commenting",
    )
    op.create_index(
        "ix_channel_alerts_campaign_id",
        "channel_alerts",
        ["campaign_id"],
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_index("ix_channel_alerts_campaign_id", table_name="channel_alerts", schema="commenting")
    op.drop_index("ix_channel_alerts_open", table_name="channel_alerts", schema="commenting")
    op.drop_table("channel_alerts", schema="commenting")
    op.drop_index(
        "ix_monitored_channels_source_campaign_id",
        table_name="monitored_channels",
        schema="commenting",
    )
    op.drop_column("monitored_channels", "source_campaign_id", schema="commenting")
