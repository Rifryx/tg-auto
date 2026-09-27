"""priming: campaigns, campaign_accounts, campaign_targets

Первый набор таблиц модуля прайминга (docs/priming-spec.md §4.1–4.3;
промпт 1.3 из docs/priming-prompts.md).

Заметки:
* Все таблицы в схеме ``priming`` (создана миграцией 0039).
* ``campaign_accounts.profile_preset_id`` и ``campaign_targets.source_id`` —
  колонки без FK-констрейнтов: их таблицы (``priming.profile_presets`` и
  ``priming.target_sources``) заводятся следующей миграцией (1.4), там же
  добавятся FK через ``op.create_foreign_key``.

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIMING = "priming"

_CAMPAIGN_STATUS_VALUES = (
    "draft", "queued", "running", "paused", "stopped", "finished", "failed",
)
_MODE_VALUES = ("priming",)
_TRIGGER_ACTIONS = (
    "set_ttl_1d", "set_ttl_off", "set_content_protection",
    "secret_chat_request", "contact_added", "contact_removed",
    "pinned_message_ping",
)
_HUMANIZER_MODES = ("off", "balanced", "aggressive")
_WARMUP_PROFILES = ("cold", "warm", "hot")
_ACCOUNT_STATES = ("idle", "working", "cooldown", "quarantined", "disabled")
_TARGET_STATUSES = (
    "pending", "assigned", "primed", "failed", "skipped", "blacklisted",
)
_LAST_SEEN = ("recently", "within_week", "within_month", "long_ago", "unknown")


def _in_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # ------------------------------------------------------- campaigns
    op.create_table(
        "campaigns",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(), nullable=False, server_default="priming"),
        sa.Column("trigger_action", sa.String(), nullable=False),
        sa.Column("humanizer_mode", sa.String(), nullable=False, server_default="balanced"),
        sa.Column("delay_between_targets_sec_min", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("delay_between_targets_sec_max", sa.Integer(), nullable=False, server_default="180"),
        sa.Column("flood_wait_pause_sec", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("max_flood_waits_per_account", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("daily_limit_per_account", sa.Integer(), nullable=False, server_default="35"),
        sa.Column("warmup_profile", sa.String(), nullable=False, server_default="warm"),
        sa.Column("require_username", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("premium_only", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("exclude_bots", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("exclude_deleted", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("exclude_admins", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("stop_on_privacy_rate", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"status IN ({_in_sql(_CAMPAIGN_STATUS_VALUES)})",
                           name="ck_campaigns_status_allowed"),
        sa.CheckConstraint(f"mode IN ({_in_sql(_MODE_VALUES)})",
                           name="ck_campaigns_mode_allowed"),
        sa.CheckConstraint(f"trigger_action IN ({_in_sql(_TRIGGER_ACTIONS)})",
                           name="ck_campaigns_trigger_action_allowed"),
        sa.CheckConstraint(f"humanizer_mode IN ({_in_sql(_HUMANIZER_MODES)})",
                           name="ck_campaigns_humanizer_mode_allowed"),
        sa.CheckConstraint(f"warmup_profile IN ({_in_sql(_WARMUP_PROFILES)})",
                           name="ck_campaigns_warmup_profile_allowed"),
        sa.CheckConstraint(
            "delay_between_targets_sec_min >= 0 "
            "AND delay_between_targets_sec_max >= delay_between_targets_sec_min",
            name="ck_campaigns_delay_range_valid",
        ),
        sa.CheckConstraint("flood_wait_pause_sec > 0",
                           name="ck_campaigns_flood_wait_pause_valid"),
        sa.CheckConstraint("max_flood_waits_per_account > 0",
                           name="ck_campaigns_max_flood_waits_valid"),
        sa.CheckConstraint(
            "daily_limit_per_account >= 1 AND daily_limit_per_account <= 500",
            name="ck_campaigns_daily_limit_valid",
        ),
        sa.CheckConstraint(
            "stop_on_privacy_rate >= 0 AND stop_on_privacy_rate <= 1",
            name="ck_campaigns_stop_on_privacy_rate_valid",
        ),
        schema=PRIMING,
    )

    # ----------------------------------------------- campaign_accounts
    op.create_table(
        "campaign_accounts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="idle"),
        sa.Column("flood_waits_consecutive", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("flood_waits_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("primes_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("primes_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_prime_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_available_at", sa.DateTime(timezone=True), nullable=True),
        # FK на priming.profile_presets будет создан миграцией 0041.
        sa.Column("profile_preset_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["campaign_id"], [f"{PRIMING}.campaigns.id"],
            name="fk_campaign_accounts_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"],
            name="fk_campaign_accounts_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "campaign_id", "account_id",
            name="uq_campaign_accounts_campaign_id_account_id",
        ),
        sa.CheckConstraint(f"state IN ({_in_sql(_ACCOUNT_STATES)})",
                           name="ck_campaign_accounts_state_allowed"),
        sa.CheckConstraint(
            "flood_waits_consecutive >= 0 AND flood_waits_total >= 0",
            name="ck_campaign_accounts_flood_counters_nonneg",
        ),
        sa.CheckConstraint(
            "primes_today >= 0 AND primes_total >= 0",
            name="ck_campaign_accounts_prime_counters_nonneg",
        ),
        schema=PRIMING,
    )

    # ------------------------------------------------ campaign_targets
    op.create_table(
        "campaign_targets",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        # FK на priming.target_sources будет создан миграцией 0041.
        sa.Column("source_id", sa.BigInteger(), nullable=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("has_premium", sa.Boolean(), nullable=True),
        sa.Column("last_seen_bucket", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("assigned_account_id", sa.BigInteger(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("primed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["campaign_id"], [f"{PRIMING}.campaigns.id"],
            name="fk_campaign_targets_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_account_id"], ["accounts.id"],
            name="fk_campaign_targets_assigned_account_id_accounts",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(f"status IN ({_in_sql(_TARGET_STATUSES)})",
                           name="ck_campaign_targets_status_allowed"),
        sa.CheckConstraint(f"last_seen_bucket IN ({_in_sql(_LAST_SEEN)})",
                           name="ck_campaign_targets_last_seen_bucket_allowed"),
        sa.CheckConstraint(
            "tg_user_id IS NOT NULL OR username IS NOT NULL OR phone IS NOT NULL",
            name="ck_campaign_targets_identity_present",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_campaign_targets_attempts_nonneg"),
        schema=PRIMING,
    )

    # Индексы, читающие «следующая свободная цель по кампании» — единственный
    # горячий путь orchestrator'а (промпт 2.3).
    op.create_index(
        "ix_campaign_targets_campaign_status",
        "campaign_targets",
        ["campaign_id", "status"],
        schema=PRIMING,
    )
    op.create_index(
        "ix_campaign_targets_campaign_tg_user",
        "campaign_targets",
        ["campaign_id", "tg_user_id"],
        unique=True,
        schema=PRIMING,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_campaign_targets_campaign_tg_user",
        table_name="campaign_targets",
        schema=PRIMING,
    )
    op.drop_index(
        "ix_campaign_targets_campaign_status",
        table_name="campaign_targets",
        schema=PRIMING,
    )
    op.drop_table("campaign_targets", schema=PRIMING)
    op.drop_table("campaign_accounts", schema=PRIMING)
    op.drop_table("campaigns", schema=PRIMING)
