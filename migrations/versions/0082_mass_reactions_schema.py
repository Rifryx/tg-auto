"""mass_reactions: schema + таблицы кампаний масс-реакций.

Шаг 1 модуля «Масс-реакции» (spec): схема Postgres ``mass_reactions`` и четыре
таблицы — campaigns, campaign_accounts, campaign_chats, execution_log. Воркер,
источник чатов и экран — отдельными миграциями/PR.

Revision ID: 0082
Revises: 0081
Create Date: 2026-11-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0082"
down_revision: Union[str, None] = "0081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "mass_reactions"

_STATUS = "('draft','queued','running','paused','stopped','finished','failed')"
_SOURCE = "('by_subscriptions','explicit_list')"
_STRATEGY = "('random','round_robin')"
_WARMUP = "('cold','warm','hot')"
_HUMANIZER = "('off','balanced','aggressive')"
_ACCT_STATE = "('idle','working','cooldown','quarantined','disabled')"
_CHAT_STATE = "('pending','active','not_subscribed','joining','failed','disabled')"
_NOTIFY = "('notify_only','notify_and_join')"
_OUTCOME = (
    "('reacted','skipped_not_human','skipped_filter','skipped_quiet',"
    "'flood_wait','peer_flood','forbidden','not_found','internal_error')"
)


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    op.create_table(
        "campaigns",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column(
            "chat_source_mode", sa.String(), nullable=False,
            server_default="by_subscriptions",
        ),
        sa.Column("reaction_emojis", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reaction_strategy", sa.String(), nullable=False, server_default="random"),
        sa.Column("every_n_message", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("probability_percent", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("first_n_in_burst", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("duration_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("skip_messages_older_than_days", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("delay_between_reactions_sec_min", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("delay_between_reactions_sec_max", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("join_pause_sec", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("warmup_profile", sa.String(), nullable=False, server_default="warm"),
        sa.Column("humanizer_mode", sa.String(), nullable=False, server_default="balanced"),
        sa.Column("daily_limit_per_account", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("max_chats_per_account", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("flood_wait_pause_sec", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("max_flood_waits_per_account", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("quiet_hours_start", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quiet_hours_end", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(f"status IN {_STATUS}", name="ck_campaigns_status_allowed"),
        sa.CheckConstraint(f"chat_source_mode IN {_SOURCE}", name="ck_campaigns_chat_source_mode_allowed"),
        sa.CheckConstraint(f"reaction_strategy IN {_STRATEGY}", name="ck_campaigns_reaction_strategy_allowed"),
        sa.CheckConstraint(f"warmup_profile IN {_WARMUP}", name="ck_campaigns_warmup_profile_allowed"),
        sa.CheckConstraint(f"humanizer_mode IN {_HUMANIZER}", name="ck_campaigns_humanizer_mode_allowed"),
        sa.CheckConstraint("jsonb_array_length(reaction_emojis) >= 1", name="ck_campaigns_reaction_emojis_nonempty"),
        sa.CheckConstraint("every_n_message >= 1 AND every_n_message <= 50", name="ck_campaigns_every_n_message_valid"),
        sa.CheckConstraint("probability_percent >= 1 AND probability_percent <= 100", name="ck_campaigns_probability_percent_valid"),
        sa.CheckConstraint("first_n_in_burst >= 1 AND first_n_in_burst <= 10", name="ck_campaigns_first_n_in_burst_valid"),
        sa.CheckConstraint("duration_hours >= 1 AND duration_hours <= 72", name="ck_campaigns_duration_hours_valid"),
        sa.CheckConstraint("skip_messages_older_than_days >= 0 AND skip_messages_older_than_days <= 30", name="ck_campaigns_skip_older_days_valid"),
        sa.CheckConstraint("delay_between_reactions_sec_min >= 0 AND delay_between_reactions_sec_max >= delay_between_reactions_sec_min", name="ck_campaigns_delay_range_valid"),
        sa.CheckConstraint("join_pause_sec >= 0", name="ck_campaigns_join_pause_sec_valid"),
        sa.CheckConstraint("daily_limit_per_account >= 1 AND daily_limit_per_account <= 500", name="ck_campaigns_daily_limit_valid"),
        sa.CheckConstraint("max_chats_per_account >= 1 AND max_chats_per_account <= 20", name="ck_campaigns_max_chats_per_account_valid"),
        sa.CheckConstraint("flood_wait_pause_sec > 0", name="ck_campaigns_flood_wait_pause_valid"),
        sa.CheckConstraint("max_flood_waits_per_account > 0", name="ck_campaigns_max_flood_waits_valid"),
        sa.CheckConstraint("quiet_hours_start >= 0 AND quiet_hours_start < 24 AND quiet_hours_end > quiet_hours_start AND quiet_hours_end <= 24", name="ck_campaigns_quiet_hours_window_valid"),
        schema=SCHEMA,
    )

    op.create_table(
        "campaign_accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="idle"),
        sa.Column("flood_waits_consecutive", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("flood_waits_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reactions_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reactions_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reaction_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warmup_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["campaign_id"], [f"{SCHEMA}.campaigns.id"], ondelete="CASCADE", name="fk_campaign_accounts_campaign_id_campaigns"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE", name="fk_campaign_accounts_account_id_accounts"),
        sa.UniqueConstraint("campaign_id", "account_id", name="uq_campaign_accounts_campaign_id_account_id"),
        sa.CheckConstraint(f"state IN {_ACCT_STATE}", name="ck_campaign_accounts_state_allowed"),
        sa.CheckConstraint("flood_waits_consecutive >= 0 AND flood_waits_total >= 0", name="ck_campaign_accounts_flood_counters_nonneg"),
        sa.CheckConstraint("reactions_today >= 0 AND reactions_total >= 0", name="ck_campaign_accounts_reaction_counters_nonneg"),
        schema=SCHEMA,
    )

    op.create_table(
        "campaign_chats",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=True),
        sa.Column("chat_ref", sa.String(length=255), nullable=False),
        sa.Column("chat_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="pending"),
        sa.Column("notify_mode", sa.String(), nullable=False, server_default="notify_only"),
        sa.Column("reaction_counter", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reactions_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["campaign_id"], [f"{SCHEMA}.campaigns.id"], ondelete="CASCADE", name="fk_campaign_chats_campaign_id_campaigns"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL", name="fk_campaign_chats_account_id_accounts"),
        sa.UniqueConstraint("campaign_id", "chat_ref", name="uq_campaign_chats_campaign_id_chat_ref"),
        sa.CheckConstraint(f"state IN {_CHAT_STATE}", name="ck_campaign_chats_state_allowed"),
        sa.CheckConstraint(f"notify_mode IN {_NOTIFY}", name="ck_campaign_chats_notify_mode_allowed"),
        sa.CheckConstraint("reaction_counter >= 0 AND reactions_total >= 0", name="ck_campaign_chats_chat_counters_nonneg"),
        schema=SCHEMA,
    )

    op.create_table(
        "execution_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("emoji", sa.String(length=16), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("flood_wait_sec", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["campaign_id"], [f"{SCHEMA}.campaigns.id"], ondelete="CASCADE", name="fk_execution_log_campaign_id_campaigns"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE", name="fk_execution_log_account_id_accounts"),
        sa.ForeignKeyConstraint(["chat_id"], [f"{SCHEMA}.campaign_chats.id"], ondelete="CASCADE", name="fk_execution_log_chat_id_campaign_chats"),
        sa.CheckConstraint(f"outcome IN {_OUTCOME}", name="ck_execution_log_outcome_allowed"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_execution_log_latency_ms_nonneg"),
        sa.CheckConstraint("flood_wait_sec IS NULL OR flood_wait_sec > 0", name="ck_execution_log_flood_wait_sec_valid"),
        schema=SCHEMA,
    )
    op.create_index("ix_mr_execution_log_campaign_started", "execution_log", ["campaign_id", "started_at"], schema=SCHEMA)
    op.create_index("ix_mr_execution_log_campaign_outcome", "execution_log", ["campaign_id", "outcome"], schema=SCHEMA)


def downgrade() -> None:
    op.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
