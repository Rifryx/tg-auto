"""Режимы отбора постов + режимы работы кампании (§ Этап 2).

* ``campaigns.post_selection_mode`` ∈ (all | keywords | probability)
  + ``keywords`` (ARRAY text) + ``probability_percent`` (0..100).
* ``campaigns.post_scope`` ∈ (new | existing | mixed) — new = только новые
  посты через listener; existing = одноразовый backfill (см. DEFERRED-FEATURES
  → [E2.1]); mixed = и то, и другое.
* ``campaigns.work_mode`` ∈ (by_count | by_time_window) + лимиты
  ``max_comments`` / ``min_words`` / ``window_after_post_sec`` /
  ``pause_between_sec``.
* ``campaign_accounts.probability_override`` (0..100 или NULL) — пер-аккаунтный
  тумблер для режима probability.

Runtime-эффект в этой миграции:
- listener фильтрует по keywords и делает коин-флип по probability_percent
  (см. modules/commenting/worker/listener.py).
- Остальные лимиты (max_comments, min_words retry-loop, окна и паузы,
  backfill existing/mixed) — заготовки на runner, см. DEFERRED-FEATURES.

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-22
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- campaigns: режимы отбора постов -----------------------------------
    op.add_column(
        "campaigns",
        sa.Column(
            "post_selection_mode",
            sa.String(),
            nullable=False,
            server_default="all",
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "keywords",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "probability_percent",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column("post_scope", sa.String(), nullable=False, server_default="new"),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "work_mode", sa.String(), nullable=False, server_default="by_count"
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column("max_comments", sa.Integer(), nullable=True),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "min_words", sa.Integer(), nullable=False, server_default="0"
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column("window_after_post_sec", sa.Integer(), nullable=True),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column("pause_between_sec", sa.Integer(), nullable=True),
        schema="commenting",
    )
    for name, expr in [
        (
            "campaign_post_selection_mode_allowed",
            "post_selection_mode IN ('all', 'keywords', 'probability')",
        ),
        (
            "campaign_probability_percent_valid",
            "probability_percent BETWEEN 0 AND 100",
        ),
        ("campaign_work_mode_allowed", "work_mode IN ('by_count', 'by_time_window')"),
        ("campaign_post_scope_allowed", "post_scope IN ('new', 'existing', 'mixed')"),
        ("campaign_min_words_valid", "min_words >= 0"),
        (
            "campaign_max_comments_valid",
            "max_comments IS NULL OR max_comments > 0",
        ),
        (
            "campaign_window_after_post_valid",
            "window_after_post_sec IS NULL OR window_after_post_sec > 0",
        ),
        (
            "campaign_pause_between_valid",
            "pause_between_sec IS NULL OR pause_between_sec >= 0",
        ),
    ]:
        op.create_check_constraint(name, "campaigns", expr, schema="commenting")

    # --- campaign_accounts: probability_override --------------------------
    op.add_column(
        "campaign_accounts",
        sa.Column("probability_override", sa.Integer(), nullable=True),
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_accounts_probability_override_valid",
        "campaign_accounts",
        "probability_override IS NULL OR probability_override BETWEEN 0 AND 100",
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_constraint(
        "campaign_accounts_probability_override_valid",
        "campaign_accounts",
        type_="check",
        schema="commenting",
    )
    op.drop_column("campaign_accounts", "probability_override", schema="commenting")
    for name in [
        "campaign_pause_between_valid",
        "campaign_window_after_post_valid",
        "campaign_max_comments_valid",
        "campaign_min_words_valid",
        "campaign_post_scope_allowed",
        "campaign_work_mode_allowed",
        "campaign_probability_percent_valid",
        "campaign_post_selection_mode_allowed",
    ]:
        op.drop_constraint(name, "campaigns", type_="check", schema="commenting")
    for col in [
        "pause_between_sec",
        "window_after_post_sec",
        "min_words",
        "max_comments",
        "work_mode",
        "post_scope",
        "probability_percent",
        "keywords",
        "post_selection_mode",
    ]:
        op.drop_column("campaigns", col, schema="commenting")
