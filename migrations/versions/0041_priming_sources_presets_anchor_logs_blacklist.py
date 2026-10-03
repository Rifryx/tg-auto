"""priming: target_sources, profile_presets, anchor_channels,
execution_log, flood_incidents, blacklist (+ FK на forward-refs)

Вторая волна таблиц модуля прайминга (docs/priming-spec.md §4.4–4.9;
промпт 1.4). Плюс — добавляем FK-констрейнты в forward-ref-колонки
предыдущей миграции:

* ``campaign_accounts.profile_preset_id`` → ``profile_presets.id``
  (ON DELETE SET NULL)
* ``campaign_targets.source_id`` → ``target_sources.id``
  (ON DELETE SET NULL)

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIMING = "priming"

_PARSER_KINDS = ("chat_messages", "chat_members", "manual_list", "upload_csv")
_USERNAME_GENERATORS = ("llm", "dict", "template")
_AVATAR_SOURCES = ("upload", "service_gallery")
_ANCHOR_STATES = ("ok", "broken", "reset_required")
_TRIGGER_ACTIONS = (
    "set_ttl_1d", "set_ttl_off", "set_content_protection",
    "secret_chat_request", "contact_added", "contact_removed",
    "pinned_message_ping",
)
_OUTCOMES = (
    "primed", "already_applied", "flood_wait", "privacy_restricted",
    "deleted", "not_found", "channel_pinned_error", "skipped_quiet",
    "internal_error",
)
_BLACKLIST_REASONS = (
    "manual", "privacy_restricted", "already_primed_recently",
    "bot", "deleted", "complaint",
)


def _in_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # --------------------------------------------------- target_sources
    op.create_table(
        "target_sources",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("chat_ref", sa.String(), nullable=True),
        sa.Column("days_window", sa.Integer(), nullable=True),
        sa.Column("min_messages", sa.Integer(), nullable=True),
        sa.Column("raw_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("after_filters_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["campaign_id"], [f"{PRIMING}.campaigns.id"],
            name="fk_target_sources_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(f"kind IN ({_in_sql(_PARSER_KINDS)})",
                           name="ck_target_sources_kind_allowed"),
        sa.CheckConstraint(
            "raw_count >= 0 AND after_filters_count >= 0 "
            "AND after_filters_count <= raw_count",
            name="ck_target_sources_counts_valid",
        ),
        sa.CheckConstraint("days_window IS NULL OR days_window > 0",
                           name="ck_target_sources_days_window_valid"),
        sa.CheckConstraint("min_messages IS NULL OR min_messages > 0",
                           name="ck_target_sources_min_messages_valid"),
        schema=PRIMING,
    )

    # -------------------------------------------------- profile_presets
    op.create_table(
        "profile_presets",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("first_name_pool", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("last_name_pool", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("username_generator", sa.String(), nullable=False, server_default="llm"),
        sa.Column("bio_text", sa.Text(), nullable=True),
        sa.Column("bio_link", sa.String(), nullable=True),
        sa.Column("avatar_source", sa.String(), nullable=False, server_default="upload"),
        sa.Column("stories_pool_id", sa.BigInteger(), nullable=True),
        sa.Column("anchor_channel_template_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"username_generator IN ({_in_sql(_USERNAME_GENERATORS)})",
                           name="ck_profile_presets_username_generator_allowed"),
        sa.CheckConstraint(f"avatar_source IN ({_in_sql(_AVATAR_SOURCES)})",
                           name="ck_profile_presets_avatar_source_allowed"),
        schema=PRIMING,
    )
    op.create_index(
        "ix_profile_presets_owner", "profile_presets",
        ["owner_user_id"], schema=PRIMING,
    )

    # -------------------------------------------------- anchor_channels
    op.create_table(
        "anchor_channels",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("pinned_post_id", sa.BigInteger(), nullable=True),
        sa.Column("pinned_post_text", sa.Text(), nullable=True),
        sa.Column("attached_to_profile_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="ok"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"],
            name="fk_anchor_channels_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("account_id", name="uq_anchor_channels_account_id"),
        sa.CheckConstraint(f"state IN ({_in_sql(_ANCHOR_STATES)})",
                           name="ck_anchor_channels_state_allowed"),
        schema=PRIMING,
    )

    # ---------------------------------------------------- execution_log
    op.create_table(
        "execution_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("flood_wait_sec", sa.Integer(), nullable=True),
        sa.Column("trigger_action", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"], [f"{PRIMING}.campaigns.id"],
            name="fk_execution_log_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"],
            name="fk_execution_log_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"], [f"{PRIMING}.campaign_targets.id"],
            name="fk_execution_log_target_id_campaign_targets",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(f"outcome IN ({_in_sql(_OUTCOMES)})",
                           name="ck_execution_log_outcome_allowed"),
        sa.CheckConstraint(f"trigger_action IN ({_in_sql(_TRIGGER_ACTIONS)})",
                           name="ck_execution_log_trigger_action_allowed"),
        sa.CheckConstraint("latency_ms >= 0",
                           name="ck_execution_log_latency_ms_nonneg"),
        sa.CheckConstraint(
            "flood_wait_sec IS NULL OR flood_wait_sec > 0",
            name="ck_execution_log_flood_wait_sec_valid",
        ),
        schema=PRIMING,
    )
    op.create_index(
        "ix_execution_log_campaign_started", "execution_log",
        ["campaign_id", "started_at"], schema=PRIMING,
    )
    op.create_index(
        "ix_execution_log_campaign_outcome", "execution_log",
        ["campaign_id", "outcome"], schema=PRIMING,
    )

    # -------------------------------------------------- flood_incidents
    op.create_table(
        "flood_incidents",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("campaign_account_id", sa.BigInteger(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("flood_wait_sec", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_account_id"], [f"{PRIMING}.campaign_accounts.id"],
            name="fk_flood_incidents_campaign_account_id_campaign_accounts",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("flood_wait_sec > 0",
                           name="ck_flood_incidents_flood_wait_sec_positive"),
        schema=PRIMING,
    )
    op.create_index(
        "ix_flood_incidents_campaign_account_at", "flood_incidents",
        ["campaign_account_id", "at"], schema=PRIMING,
    )

    # -------------------------------------------------------- blacklist
    op.create_table(
        "blacklist",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"reason IN ({_in_sql(_BLACKLIST_REASONS)})",
                           name="ck_blacklist_reason_allowed"),
        sa.CheckConstraint(
            "tg_user_id IS NOT NULL OR username IS NOT NULL OR phone IS NOT NULL",
            name="ck_blacklist_identity_present",
        ),
        schema=PRIMING,
    )
    op.create_index(
        "ix_blacklist_owner_tg_user_id", "blacklist",
        ["owner_user_id", "tg_user_id"], schema=PRIMING,
    )
    op.create_index(
        "ix_blacklist_owner_username", "blacklist",
        ["owner_user_id", "username"], schema=PRIMING,
    )
    op.create_index(
        "ix_blacklist_owner_phone", "blacklist",
        ["owner_user_id", "phone"], schema=PRIMING,
    )

    # ----------- FK на forward-refs из миграции 0040 ------------------
    op.create_foreign_key(
        "fk_campaign_accounts_profile_preset_id_profile_presets",
        source_table="campaign_accounts",
        referent_table="profile_presets",
        local_cols=["profile_preset_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
        source_schema=PRIMING,
        referent_schema=PRIMING,
    )
    op.create_foreign_key(
        "fk_campaign_targets_source_id_target_sources",
        source_table="campaign_targets",
        referent_table="target_sources",
        local_cols=["source_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
        source_schema=PRIMING,
        referent_schema=PRIMING,
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_campaign_targets_source_id_target_sources",
        "campaign_targets", type_="foreignkey", schema=PRIMING,
    )
    op.drop_constraint(
        "fk_campaign_accounts_profile_preset_id_profile_presets",
        "campaign_accounts", type_="foreignkey", schema=PRIMING,
    )

    for idx in (
        "ix_blacklist_owner_phone",
        "ix_blacklist_owner_username",
        "ix_blacklist_owner_tg_user_id",
    ):
        op.drop_index(idx, table_name="blacklist", schema=PRIMING)
    op.drop_table("blacklist", schema=PRIMING)

    op.drop_index(
        "ix_flood_incidents_campaign_account_at",
        table_name="flood_incidents", schema=PRIMING,
    )
    op.drop_table("flood_incidents", schema=PRIMING)

    for idx in (
        "ix_execution_log_campaign_outcome",
        "ix_execution_log_campaign_started",
    ):
        op.drop_index(idx, table_name="execution_log", schema=PRIMING)
    op.drop_table("execution_log", schema=PRIMING)

    op.drop_table("anchor_channels", schema=PRIMING)
    op.drop_index("ix_profile_presets_owner", table_name="profile_presets", schema=PRIMING)
    op.drop_table("profile_presets", schema=PRIMING)
    op.drop_table("target_sources", schema=PRIMING)
