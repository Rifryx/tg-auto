"""Тумблер «мониторить всё, что на аккаунте» для НейроШиллинга.

Пользователю не всегда удобно вручную перечислять каналы для мониторинга:
хочется включить тумблер — и софт сам соберёт каналы аккаунта-парсера и
будет следить за новыми постами в них.

* ``campaigns.monitor_all_dialogs`` — сам тумблер. Когда включён, поллер
  (poll_channel_monitors) перечисляет broadcast-каналы аккаунта кампании и
  заводит на них channel_monitor-цели автоматически.
* ``campaign_targets.auto_discovered`` — помечает такие авто-цели, чтобы
  отличать их от введённых руками: при выключении тумблера их чистим, в UI
  показываем значком «авто» и не даём редактировать поштучно.

Revision ID: 0074
Revises: 0073
Create Date: 2026-11-06
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0074"
down_revision: Union[str, None] = "0073"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "monitor_all_dialogs",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="shilling",
    )
    op.add_column(
        "campaign_targets",
        sa.Column(
            "auto_discovered",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="shilling",
    )


def downgrade() -> None:
    op.drop_column("campaign_targets", "auto_discovered", schema="shilling")
    op.drop_column("campaigns", "monitor_all_dialogs", schema="shilling")
