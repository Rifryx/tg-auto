"""initial schema: shared + commenting module

Revision ID: 0001
Revises:
Create Date: 2026-09-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COMMENTING = "commenting"


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{COMMENTING}"')

    # ------------------------------------------------------------------ proxies
    op.create_table(
        "proxies",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("login", sa.String(), nullable=True),
        sa.Column("password_enc", sa.LargeBinary(), nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("geo", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="unchecked"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("type IN ('socks5', 'http')", name="type_allowed"),
        sa.CheckConstraint(
            "status IN ('alive', 'dead', 'unchecked')", name="status_allowed"
        ),
    )
    op.create_index("ix_proxies_status", "proxies", ["status"])

    # ----------------------------------------------------------------- personas
    op.create_table(
        "personas",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("avatar_template_url", sa.String(), nullable=True),
        sa.Column("bio_template", sa.String(), nullable=True),
        sa.Column("personality_tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ----------------------------------------------------------------- accounts
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("bio", sa.String(), nullable=True),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("session_enc", sa.LargeBinary(), nullable=False),
        sa.Column("proxy_id", sa.BigInteger(), nullable=True),
        sa.Column("persona_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="created"),
        sa.Column("previous_status", sa.String(), nullable=True),
        sa.Column("assigned_container_type", sa.String(), nullable=True),
        sa.Column("assigned_container_id", sa.BigInteger(), nullable=True),
        sa.Column("warming_profile", sa.String(), nullable=False, server_default="medium"),
        sa.Column("warming_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_model", sa.String(), nullable=False),
        sa.Column("system_version", sa.String(), nullable=False),
        sa.Column("app_version", sa.String(), nullable=False),
        sa.Column("lang_code", sa.String(), nullable=False),
        sa.Column("system_lang_code", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("phone", name="uq_accounts_phone"),
        sa.ForeignKeyConstraint(
            ["proxy_id"], ["proxies.id"], name="fk_accounts_proxy_id_proxies", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"], ["personas.id"], name="fk_accounts_persona_id_personas", ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN ('created', 'warming', 'pool', 'assigned', 'cooldown', 'retired', 'banned')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "warming_profile IN ('minimal', 'medium', 'dense')",
            name="warming_profile_allowed",
        ),
        sa.CheckConstraint(
            "(assigned_container_type IS NULL) = (assigned_container_id IS NULL)",
            name="assignment_pair_consistent",
        ),
    )
    op.create_index("ix_accounts_status", "accounts", ["status"])
    op.create_index("ix_accounts_proxy_id", "accounts", ["proxy_id"])
    op.create_index("ix_accounts_persona_id", "accounts", ["persona_id"])
    op.create_index(
        "ix_accounts_assigned_container",
        "accounts",
        ["assigned_container_type", "assigned_container_id"],
    )
    op.create_index(
        "ix_accounts_pool_warming_profile",
        "accounts",
        ["status", "warming_profile"],
        postgresql_where=sa.text("status = 'pool'"),
    )
    op.create_index(
        "ix_accounts_cooldown_until",
        "accounts",
        ["cooldown_until"],
        postgresql_where=sa.text("status = 'cooldown'"),
    )

    # -------------------------------------------------------- warming_activities
    op.create_table(
        "warming_activities",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"],
            name="fk_warming_activities_account_id_accounts", ondelete="CASCADE",
        ),
        sa.CheckConstraint("kind IN ('initial', 'maintenance')", name="kind_allowed"),
        sa.CheckConstraint(
            "action_type IN ('subscribe_channel', 'read_history', 'reaction', "
            "'view_media', 'join_group', 'idle_online', 'update_profile')",
            name="action_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('done', 'failed', 'skipped')", name="status_allowed"
        ),
    )
    op.create_index(
        "ix_warming_activities_account_id_created_at",
        "warming_activities",
        ["account_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_warming_activities_kind_created_at",
        "warming_activities",
        ["kind", "created_at"],
    )

    # ------------------------------------------------------------- health_events
    op.create_table(
        "health_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("triggered_status_change", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"],
            name="fk_health_events_account_id_accounts", ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "event_type IN ('flood_wait', 'spam_block', 'restricted', "
            "'proxy_down', 'session_revoked', 'auth_failed')",
            name="event_type_allowed",
        ),
    )
    op.create_index(
        "ix_health_events_account_id_created_at",
        "health_events",
        ["account_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_health_events_unresolved",
        "health_events",
        ["resolved"],
        postgresql_where=sa.text("resolved = false"),
    )

    # ------------------------------------------------- account_status_history
    op.create_table(
        "account_status_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("from_status", sa.String(), nullable=True),
        sa.Column("to_status", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("initiator", sa.String(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"],
            name="fk_account_status_history_account_id_accounts", ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "initiator IN ('user', 'auto', 'health')",
            name="initiator_allowed",
        ),
    )
    op.create_index(
        "ix_account_status_history_account_id_created_at",
        "account_status_history",
        ["account_id", sa.text("created_at DESC")],
    )

    # ================================================== commenting.* ==========

    op.create_table(
        "campaigns",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("target_channel", sa.String(), nullable=False),
        sa.Column("discussion_group_id", sa.BigInteger(), nullable=True),
        sa.Column("base_system_prompt", sa.String(), nullable=False),
        sa.Column("llm_provider", sa.String(), nullable=False),
        sa.Column("active_hours_start", sa.Time(), nullable=False),
        sa.Column("active_hours_end", sa.Time(), nullable=False),
        sa.Column("active_hours_tz", sa.String(), nullable=False),
        sa.Column("posting_delay_min_sec", sa.Integer(), nullable=False),
        sa.Column("posting_delay_max_sec", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "llm_provider IN ('deepseek', 'gemini')",
            name="llm_provider_allowed",
        ),
        sa.CheckConstraint(
            "posting_delay_min_sec >= 0 AND posting_delay_max_sec >= posting_delay_min_sec",
            name="posting_delay_range_valid",
        ),
        schema=COMMENTING,
    )

    op.create_table(
        "campaign_accounts",
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("override_prompt", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("campaign_id", "account_id", name="pk_campaign_accounts"),
        sa.UniqueConstraint("account_id", name="uq_campaign_accounts_account_id"),
        sa.ForeignKeyConstraint(
            ["campaign_id"], [f"{COMMENTING}.campaigns.id"],
            name="fk_campaign_accounts_campaign_id_campaigns", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"],
            name="fk_campaign_accounts_account_id_accounts", ondelete="CASCADE",
        ),
        schema=COMMENTING,
    )

    op.create_table(
        "comment_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("post_channel_msg_id", sa.BigInteger(), nullable=False),
        sa.Column("posted_message_id", sa.BigInteger(), nullable=True),
        sa.Column("comment_text", sa.String(), nullable=False),
        sa.Column("in_reply_to_message_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["campaign_id"], [f"{COMMENTING}.campaigns.id"],
            name="fk_comment_logs_campaign_id_campaigns", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"],
            name="fk_comment_logs_account_id_accounts", ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('posted', 'failed', 'flagged')",
            name="status_allowed",
        ),
        schema=COMMENTING,
    )
    op.create_index(
        "ix_comment_logs_campaign_id_created_at",
        "comment_logs",
        ["campaign_id", sa.text("created_at DESC")],
        schema=COMMENTING,
    )
    op.create_index(
        "ix_comment_logs_account_id_created_at",
        "comment_logs",
        ["account_id", sa.text("created_at DESC")],
        schema=COMMENTING,
    )
    op.create_index(
        "ix_comment_logs_post_channel_msg_id",
        "comment_logs",
        ["post_channel_msg_id"],
        schema=COMMENTING,
    )


def downgrade() -> None:
    op.drop_table("comment_logs", schema=COMMENTING)
    op.drop_table("campaign_accounts", schema=COMMENTING)
    op.drop_table("campaigns", schema=COMMENTING)
    op.drop_table("account_status_history")
    op.drop_table("health_events")
    op.drop_table("warming_activities")
    op.drop_table("accounts")
    op.drop_table("personas")
    op.drop_table("proxies")
    op.execute(f'DROP SCHEMA IF EXISTS "{COMMENTING}" CASCADE')
