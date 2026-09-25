"""shilling: campaign_accounts, campaign_targets, execution_logs, blacklist

Второй набор таблиц модуля НейроШиллинг (см. docs/neuroshilling-spec.md
§ 3.5–3.8). Реализует промпт 1.3.

* ``campaign_accounts`` — привязка аккаунта к кампании + роль/резерв.
* ``campaign_targets`` — целевые каналы (raw_input + resolved chat_id).
* ``execution_logs`` — история попыток отправки (для статистики/failover).
* ``blacklist`` — чёрный список чатов с partial unique-индексами.

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHILLING = "shilling"


def upgrade() -> None:
    # ------------------------------------------------ campaign_accounts
    op.create_table(
        "campaign_accounts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=True),
        sa.Column("is_reserve", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["campaign_id"], [f"{SHILLING}.campaigns.id"],
            name="fk_campaign_accounts_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"],
            name="fk_campaign_accounts_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], [f"{SHILLING}.scenario_roles.id"],
            name="fk_campaign_accounts_role_id_scenario_roles",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "campaign_id", "account_id",
            name="uq_campaign_accounts_campaign_id_account_id",
        ),
        schema=SHILLING,
    )
    op.create_index(
        "ix_shilling_campaign_accounts_campaign_id_is_reserve",
        "campaign_accounts",
        ["campaign_id", "is_reserve"],
        schema=SHILLING,
    )

    # -------------------------------------------------- campaign_targets
    op.create_table(
        "campaign_targets",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_input", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="username"),
        sa.Column("resolved_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["campaign_id"], [f"{SHILLING}.campaigns.id"],
            name="fk_campaign_targets_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "campaign_id", "raw_input",
            name="uq_campaign_targets_campaign_id_raw_input",
        ),
        sa.CheckConstraint(
            "kind IN ('username', 'invite', 'chat_id')",
            name="ck_campaign_targets_kind_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'error')",
            name="ck_campaign_targets_status_allowed",
        ),
        schema=SHILLING,
    )
    op.create_index(
        "ix_shilling_campaign_targets_campaign_id_status",
        "campaign_targets",
        ["campaign_id", "status"],
        schema=SHILLING,
    )

    # --------------------------------------------------- execution_logs
    op.create_table(
        "execution_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=True),
        sa.Column("step_id", sa.BigInteger(), nullable=True),
        sa.Column("message_text", sa.Text(), nullable=True),
        sa.Column("posted_message_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["campaign_id"], [f"{SHILLING}.campaigns.id"],
            name="fk_execution_logs_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"], [f"{SHILLING}.campaign_targets.id"],
            name="fk_execution_logs_target_id_campaign_targets",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"],
            name="fk_execution_logs_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], [f"{SHILLING}.scenario_roles.id"],
            name="fk_execution_logs_role_id_scenario_roles",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"], [f"{SHILLING}.scenario_steps.id"],
            name="fk_execution_logs_step_id_scenario_steps",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('sent', 'failed', 'skipped', 'replaced')",
            name="ck_execution_logs_status_allowed",
        ),
        schema=SHILLING,
    )
    op.create_index(
        "ix_shilling_execution_logs_campaign_id_created_at",
        "execution_logs",
        ["campaign_id", sa.text("created_at DESC")],
        schema=SHILLING,
    )
    op.create_index(
        "ix_shilling_execution_logs_account_id_created_at",
        "execution_logs",
        ["account_id", sa.text("created_at DESC")],
        schema=SHILLING,
    )
    op.create_index(
        "ix_shilling_execution_logs_status",
        "execution_logs",
        ["status"],
        schema=SHILLING,
    )

    # ---------------------------------------------------------- blacklist
    op.create_table(
        "blacklist",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("auto", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["campaign_id"], [f"{SHILLING}.campaigns.id"],
            name="fk_blacklist_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "chat_id IS NOT NULL OR username IS NOT NULL",
            name="ck_blacklist_identifier_present",
        ),
        schema=SHILLING,
    )
    op.create_index(
        "uq_blacklist_campaign_id_chat_id",
        "blacklist",
        ["campaign_id", "chat_id"],
        unique=True,
        postgresql_where=sa.text("chat_id IS NOT NULL"),
        schema=SHILLING,
    )
    op.create_index(
        "uq_blacklist_campaign_id_username",
        "blacklist",
        ["campaign_id", "username"],
        unique=True,
        postgresql_where=sa.text("username IS NOT NULL"),
        schema=SHILLING,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_blacklist_campaign_id_username",
        table_name="blacklist",
        schema=SHILLING,
    )
    op.drop_index(
        "uq_blacklist_campaign_id_chat_id",
        table_name="blacklist",
        schema=SHILLING,
    )
    op.drop_table("blacklist", schema=SHILLING)

    op.drop_index(
        "ix_shilling_execution_logs_status",
        table_name="execution_logs",
        schema=SHILLING,
    )
    op.drop_index(
        "ix_shilling_execution_logs_account_id_created_at",
        table_name="execution_logs",
        schema=SHILLING,
    )
    op.drop_index(
        "ix_shilling_execution_logs_campaign_id_created_at",
        table_name="execution_logs",
        schema=SHILLING,
    )
    op.drop_table("execution_logs", schema=SHILLING)

    op.drop_index(
        "ix_shilling_campaign_targets_campaign_id_status",
        table_name="campaign_targets",
        schema=SHILLING,
    )
    op.drop_table("campaign_targets", schema=SHILLING)

    op.drop_index(
        "ix_shilling_campaign_accounts_campaign_id_is_reserve",
        table_name="campaign_accounts",
        schema=SHILLING,
    )
    op.drop_table("campaign_accounts", schema=SHILLING)
