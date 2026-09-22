"""Пресеты нейрокомментинга (§ Этап 1).

* ``commenting.account_presets`` — пользовательские «рабочие наборы»
  аккаунтов. FK на accounts НЕ ставим, чтобы удаление аккаунта не
  ломало пресет (чистим лениво).
* ``commenting.delay_presets`` — пользовательские + 3 системных пресета
  задержек (Мин / Рекомендуемые / Макс). Значения соответствуют скринам
  UI-конкурента (Мин: 3–7/20–40, Реком: 50–100/80–160, Макс: 280–520/210–390).
* В ``commenting.campaigns`` появляются 4 новых поля — join-delay диапазон
  и floodwait-политика, — чтобы пресет применялся полноценно.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-22
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Новые delay-поля в campaigns ---------------------------------------
    op.add_column(
        "campaigns",
        sa.Column(
            "join_delay_min_sec",
            sa.Integer(),
            nullable=False,
            server_default="80",
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "join_delay_max_sec",
            sa.Integer(),
            nullable=False,
            server_default="160",
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "floodwait_pause_sec",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "floodwait_quarantine_max",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_join_delay_range_valid",
        "campaigns",
        "join_delay_min_sec >= 0 AND join_delay_max_sec >= join_delay_min_sec",
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_floodwait_valid",
        "campaigns",
        "floodwait_pause_sec >= 0 AND floodwait_quarantine_max >= 1",
        schema="commenting",
    )

    # --- account_presets -----------------------------------------------------
    op.create_table(
        "account_presets",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("owner_user_id", sa.String(), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "account_ids",
            postgresql.ARRAY(sa.BigInteger()),
            nullable=False,
            server_default="{}",
        ),
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
        sa.UniqueConstraint(
            "owner_user_id", "name", name="uq_account_presets_owner_name"
        ),
        schema="commenting",
    )

    # --- delay_presets -------------------------------------------------------
    op.create_table(
        "delay_presets",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        # NULL → системный пресет.
        sa.Column("owner_user_id", sa.String(), nullable=True, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("posting_delay_min_sec", sa.Integer(), nullable=False),
        sa.Column("posting_delay_max_sec", sa.Integer(), nullable=False),
        sa.Column("join_delay_min_sec", sa.Integer(), nullable=False),
        sa.Column("join_delay_max_sec", sa.Integer(), nullable=False),
        sa.Column("floodwait_pause_sec", sa.Integer(), nullable=False),
        sa.Column("floodwait_quarantine_max", sa.Integer(), nullable=False),
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
            "posting_delay_min_sec >= 0 AND "
            "posting_delay_max_sec >= posting_delay_min_sec",
            name="delay_preset_posting_range_valid",
        ),
        sa.CheckConstraint(
            "join_delay_min_sec >= 0 AND "
            "join_delay_max_sec >= join_delay_min_sec",
            name="delay_preset_join_range_valid",
        ),
        sa.CheckConstraint(
            "floodwait_pause_sec >= 0 AND floodwait_quarantine_max >= 1",
            name="delay_preset_floodwait_valid",
        ),
        sa.UniqueConstraint(
            "owner_user_id", "name", name="uq_delay_presets_owner_name"
        ),
        schema="commenting",
    )

    # --- Сид системных пресетов ---------------------------------------------
    op.execute(
        """
        INSERT INTO commenting.delay_presets
            (owner_user_id, name, is_system,
             posting_delay_min_sec, posting_delay_max_sec,
             join_delay_min_sec, join_delay_max_sec,
             floodwait_pause_sec, floodwait_quarantine_max)
        VALUES
            (NULL, 'Мин',           TRUE,   3,   7,  20,  40, 120, 3),
            (NULL, 'Рекомендуемые', TRUE,  50, 100,  80, 160, 120, 3),
            (NULL, 'Макс',          TRUE, 280, 520, 210, 390, 120, 3)
        """
    )


def downgrade() -> None:
    op.drop_table("delay_presets", schema="commenting")
    op.drop_table("account_presets", schema="commenting")
    op.drop_constraint(
        "campaign_floodwait_valid", "campaigns", type_="check", schema="commenting"
    )
    op.drop_constraint(
        "campaign_join_delay_range_valid",
        "campaigns",
        type_="check",
        schema="commenting",
    )
    op.drop_column("campaigns", "floodwait_quarantine_max", schema="commenting")
    op.drop_column("campaigns", "floodwait_pause_sec", schema="commenting")
    op.drop_column("campaigns", "join_delay_max_sec", schema="commenting")
    op.drop_column("campaigns", "join_delay_min_sec", schema="commenting")
