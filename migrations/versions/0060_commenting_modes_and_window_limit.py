"""Режим мониторинга (каналы/чаты), оконный лимит комментариев, расписание по
дням недели и негативные ключевые слова (commenting).

* ``monitor_mode``        — 'channels' (посты каналов, текущий движок) | 'chats'
  (мониторинг чатов по ключевым словам; live-рантайм подключается отдельно).
* ``max_comments_window`` — период лимита ``max_comments``: 'total' (за всю
  жизнь, как раньше) | 'hour' | 'day' | 'week'. Общая настройка.
* ``active_weekdays``     — дни недели активности (0=Пн … 6=Вс). Пусто = все дни.
* ``negative_keywords``   — стоп-слова: пост/сообщение с таким словом
  пропускается (для всех режимов отбора).

Revision ID: 0060
Revises: 0059
Create Date: 2026-10-19
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0060"
down_revision: Union[str, None] = "0059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "monitor_mode",
            sa.String(),
            nullable=False,
            server_default="channels",
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "max_comments_window",
            sa.String(),
            nullable=False,
            server_default="total",
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "active_weekdays",
            ARRAY(sa.Integer()),
            nullable=False,
            server_default=sa.text("ARRAY[]::integer[]"),
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "negative_keywords",
            ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_monitor_mode_allowed",
        "campaigns",
        "monitor_mode IN ('channels', 'chats')",
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_max_comments_window_allowed",
        "campaigns",
        "max_comments_window IN ('total', 'hour', 'day', 'week')",
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_constraint(
        "campaign_max_comments_window_allowed",
        "campaigns",
        type_="check",
        schema="commenting",
    )
    op.drop_constraint(
        "campaign_monitor_mode_allowed",
        "campaigns",
        type_="check",
        schema="commenting",
    )
    op.drop_column("campaigns", "negative_keywords", schema="commenting")
    op.drop_column("campaigns", "active_weekdays", schema="commenting")
    op.drop_column("campaigns", "max_comments_window", schema="commenting")
    op.drop_column("campaigns", "monitor_mode", schema="commenting")
