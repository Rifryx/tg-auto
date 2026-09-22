"""Целевые каналы кампании + черный список + режимы источника (§ Этап 3).

* ``campaigns.channel_source_mode`` ∈ (by_account_subscriptions | explicit_links).
* ``campaigns.on_not_subscribed_action`` ∈ (subscribe_and_notify | notify_only).
* Таблица ``commenting.campaign_channels`` — целевые каналы кампании
  (только для ``explicit_links``). Резолвер `raw_input → resolved_chat_id`
  живёт в воркере и на текущий момент отложен (см. DEFERRED-FEATURES [E3.2]).
* Таблица ``commenting.channel_blacklist`` — черный список каналов
  на кампанию. Партично-уникальные индексы по chat_id и по username,
  чтобы NULL-значения не считались дубликатами.

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-22
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- campaigns: новые режимы ------------------------------------------
    op.add_column(
        "campaigns",
        sa.Column(
            "channel_source_mode",
            sa.String(),
            nullable=False,
            server_default="explicit_links",
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "on_not_subscribed_action",
            sa.String(),
            nullable=False,
            server_default="notify_only",
        ),
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_channel_source_mode_allowed",
        "campaigns",
        "channel_source_mode IN ('by_account_subscriptions', 'explicit_links')",
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_on_not_subscribed_action_allowed",
        "campaigns",
        "on_not_subscribed_action IN ('subscribe_and_notify', 'notify_only')",
        schema="commenting",
    )

    # --- campaign_channels -------------------------------------------------
    op.create_table(
        "campaign_channels",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.BigInteger(),
            sa.ForeignKey("commenting.campaigns.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("raw_input", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("resolved_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "kind IN ('username', 'invite', 'folder')",
            name="campaign_channel_kind_allowed",
        ),
        sa.UniqueConstraint(
            "campaign_id", "raw_input", name="uq_campaign_channels_raw"
        ),
        schema="commenting",
    )

    # --- channel_blacklist -------------------------------------------------
    op.create_table(
        "channel_blacklist",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.BigInteger(),
            sa.ForeignKey("commenting.campaigns.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("auto", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "chat_id IS NOT NULL OR username IS NOT NULL",
            name="channel_blacklist_identifier_present",
        ),
        sa.UniqueConstraint(
            "campaign_id",
            "chat_id",
            "username",
            name="uq_channel_blacklist_all",
        ),
        schema="commenting",
    )
    # Частичные UNIQUE — чтобы дубли ловились и в случае с NULL в одной колонке.
    op.execute(
        "CREATE UNIQUE INDEX uq_channel_blacklist_campaign_chat "
        "ON commenting.channel_blacklist (campaign_id, chat_id) "
        "WHERE chat_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_channel_blacklist_campaign_username "
        "ON commenting.channel_blacklist (campaign_id, username) "
        "WHERE username IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index(
        "uq_channel_blacklist_campaign_username",
        table_name="channel_blacklist",
        schema="commenting",
    )
    op.drop_index(
        "uq_channel_blacklist_campaign_chat",
        table_name="channel_blacklist",
        schema="commenting",
    )
    op.drop_table("channel_blacklist", schema="commenting")
    op.drop_table("campaign_channels", schema="commenting")
    op.drop_constraint(
        "campaign_on_not_subscribed_action_allowed",
        "campaigns",
        type_="check",
        schema="commenting",
    )
    op.drop_constraint(
        "campaign_channel_source_mode_allowed",
        "campaigns",
        type_="check",
        schema="commenting",
    )
    op.drop_column("campaigns", "on_not_subscribed_action", schema="commenting")
    op.drop_column("campaigns", "channel_source_mode", schema="commenting")
