"""shilling: campaigns, scenarios, scenario_roles, scenario_steps

Первый набор таблиц модуля НейроШиллинг (см. docs/neuroshilling-spec.md
§ 3.1–3.4). Реализует промпт 1.2.

Ключевые моменты:
* Циклическая FK между ``shilling.campaigns.scenario_id`` и
  ``shilling.scenarios.campaign_id`` разрывается через ``use_alter=True``:
  FK со стороны campaigns навешивается ``ALTER TABLE`` уже после создания
  обеих таблиц, чтобы create-order не зависел от порядка.
* Все таблицы в схеме ``shilling`` (создана миграцией 0031).

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHILLING = "shilling"


def upgrade() -> None:
    # --------------------------------------------------------- campaigns
    # scenario_id FK на shilling.scenarios будем навешивать ниже
    # через ALTER TABLE (циклическая ссылка).
    op.create_table(
        "campaigns",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("brand_name", sa.String(), nullable=True),
        sa.Column("brand_link", sa.String(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("llm_provider", sa.String(), nullable=False, server_default="deepseek"),
        sa.Column("unique_messages", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("use_chat_context", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("reply_delay_min_sec", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("reply_delay_max_sec", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("target_delay_min_sec", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("target_delay_max_sec", sa.Integer(), nullable=False, server_default="1800"),
        sa.Column("posts_per_target", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("scenario_id", sa.BigInteger(), nullable=True),
        sa.Column("media_asset_id", sa.BigInteger(), nullable=True),
        sa.Column("auto_responder", sa.String(), nullable=False, server_default="off"),
        sa.Column("reserve_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("msg_limit_per_hour", sa.Integer(), nullable=True),
        sa.Column("msg_limit_total", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["media_asset_id"], ["media_assets.id"],
            name="fk_campaigns_media_asset_id_media_assets",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "llm_provider IN ('deepseek', 'gemini')",
            name="ck_campaigns_llm_provider_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'ready', 'running', 'paused', 'completed', 'error')",
            name="ck_campaigns_status_allowed",
        ),
        sa.CheckConstraint(
            "auto_responder IN ('off', 'neuro_dialogs', 'reply_in_chat')",
            name="ck_campaigns_auto_responder_allowed",
        ),
        sa.CheckConstraint(
            "reply_delay_min_sec >= 0 AND reply_delay_max_sec >= reply_delay_min_sec",
            name="ck_campaigns_reply_delay_range_valid",
        ),
        sa.CheckConstraint(
            "target_delay_min_sec >= 0 AND target_delay_max_sec >= target_delay_min_sec",
            name="ck_campaigns_target_delay_range_valid",
        ),
        sa.CheckConstraint(
            "posts_per_target >= 1",
            name="ck_campaigns_posts_per_target_valid",
        ),
        sa.CheckConstraint(
            "msg_limit_per_hour IS NULL OR msg_limit_per_hour > 0",
            name="ck_campaigns_msg_limit_per_hour_valid",
        ),
        sa.CheckConstraint(
            "msg_limit_total IS NULL OR msg_limit_total > 0",
            name="ck_campaigns_msg_limit_total_valid",
        ),
        schema=SHILLING,
    )
    op.create_index(
        "ix_shilling_campaigns_enabled_status",
        "campaigns",
        ["enabled", "status"],
        schema=SHILLING,
    )

    # --------------------------------------------------------- scenarios
    op.create_table(
        "scenarios",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("is_template", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("persons_count", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["campaign_id"], [f"{SHILLING}.campaigns.id"],
            name="fk_scenarios_campaign_id_campaigns",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "persons_count >= 2",
            name="ck_scenarios_persons_count_valid",
        ),
        schema=SHILLING,
    )
    op.create_index(
        "ix_shilling_scenarios_campaign_id",
        "scenarios",
        ["campaign_id"],
        schema=SHILLING,
    )
    op.create_index(
        "ix_shilling_scenarios_is_template",
        "scenarios",
        ["is_template"],
        schema=SHILLING,
        postgresql_where=sa.text("is_template = true"),
    )

    # Обратная FK: campaigns.scenario_id → scenarios.id (навешиваем сейчас,
    # когда таблица scenarios существует).
    op.create_foreign_key(
        "fk_campaigns_scenario_id_scenarios",
        source_table="campaigns",
        referent_table="scenarios",
        local_cols=["scenario_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
        source_schema=SHILLING,
        referent_schema=SHILLING,
    )

    # ---------------------------------------------------- scenario_roles
    op.create_table(
        "scenario_roles",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("scenario_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("character", sa.Text(), nullable=True),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["scenario_id"], [f"{SHILLING}.scenarios.id"],
            name="fk_scenario_roles_scenario_id_scenarios",
            ondelete="CASCADE",
        ),
        schema=SHILLING,
    )
    op.create_index(
        "ix_shilling_scenario_roles_scenario_id",
        "scenario_roles",
        ["scenario_id", "sort_order"],
        schema=SHILLING,
    )

    # ---------------------------------------------------- scenario_steps
    op.create_table(
        "scenario_steps",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("scenario_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(), nullable=False, server_default="message"),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("reply_to_step_id", sa.BigInteger(), nullable=True),
        sa.Column("delay_before_sec", sa.Integer(), nullable=True),
        sa.Column("reaction_emoji", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["scenario_id"], [f"{SHILLING}.scenarios.id"],
            name="fk_scenario_steps_scenario_id_scenarios",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], [f"{SHILLING}.scenario_roles.id"],
            name="fk_scenario_steps_role_id_scenario_roles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reply_to_step_id"], [f"{SHILLING}.scenario_steps.id"],
            name="fk_scenario_steps_reply_to_step_id_scenario_steps",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "step_type IN ('message', 'reaction')",
            name="ck_scenario_steps_step_type_allowed",
        ),
        sa.CheckConstraint(
            "(step_type = 'message' AND text IS NOT NULL) OR "
            "(step_type = 'reaction' AND reaction_emoji IS NOT NULL)",
            name="ck_scenario_steps_payload_matches_type",
        ),
        sa.CheckConstraint(
            "delay_before_sec IS NULL OR delay_before_sec >= 0",
            name="ck_scenario_steps_delay_before_sec_valid",
        ),
        schema=SHILLING,
    )
    op.create_index(
        "ix_shilling_scenario_steps_scenario_id_order",
        "scenario_steps",
        ["scenario_id", "step_order"],
        schema=SHILLING,
    )
    op.create_index(
        "ix_shilling_scenario_steps_role_id",
        "scenario_steps",
        ["role_id"],
        schema=SHILLING,
    )


def downgrade() -> None:
    # Порядок обратный + рвём циклическую FK ДО DROP TABLE.
    op.drop_constraint(
        "fk_campaigns_scenario_id_scenarios",
        "campaigns",
        type_="foreignkey",
        schema=SHILLING,
    )
    op.drop_index(
        "ix_shilling_scenario_steps_role_id", table_name="scenario_steps", schema=SHILLING
    )
    op.drop_index(
        "ix_shilling_scenario_steps_scenario_id_order",
        table_name="scenario_steps",
        schema=SHILLING,
    )
    op.drop_table("scenario_steps", schema=SHILLING)

    op.drop_index(
        "ix_shilling_scenario_roles_scenario_id",
        table_name="scenario_roles",
        schema=SHILLING,
    )
    op.drop_table("scenario_roles", schema=SHILLING)

    op.drop_index(
        "ix_shilling_scenarios_is_template", table_name="scenarios", schema=SHILLING
    )
    op.drop_index(
        "ix_shilling_scenarios_campaign_id", table_name="scenarios", schema=SHILLING
    )
    op.drop_table("scenarios", schema=SHILLING)

    op.drop_index(
        "ix_shilling_campaigns_enabled_status", table_name="campaigns", schema=SHILLING
    )
    op.drop_table("campaigns", schema=SHILLING)
