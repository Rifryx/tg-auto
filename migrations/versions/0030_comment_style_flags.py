"""Стиль комментариев + verify-after-post seam (§ Этап 4).

* Булевы флаги стиля: use_emojis (по умолчанию TRUE), use_stickers,
  attach_image, write_as_channel (по умолчанию FALSE).
* Verify-seam: verify_after_post + verify_delay_sec (default 300).
  См. MEMORY: monitoring-architecture — тот же аккаунт, что постил,
  проверяет через verify_delay_sec, что коммент виден в чате.

Runtime-обвязка отложена (DEFERRED-FEATURES [E4.1] / [E4.2]).

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-22
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BOOLS: list[tuple[str, str]] = [
    ("use_emojis", "true"),
    ("use_stickers", "false"),
    ("attach_image", "false"),
    ("write_as_channel", "false"),
    ("verify_after_post", "false"),
]


def upgrade() -> None:
    for name, default in _BOOLS:
        op.add_column(
            "campaigns",
            sa.Column(
                name, sa.Boolean(), nullable=False, server_default=sa.text(default)
            ),
            schema="commenting",
        )
    op.add_column(
        "campaigns",
        sa.Column(
            "verify_delay_sec",
            sa.Integer(),
            nullable=False,
            server_default="300",
        ),
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_verify_delay_valid",
        "campaigns",
        "verify_delay_sec > 0",
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_constraint(
        "campaign_verify_delay_valid",
        "campaigns",
        type_="check",
        schema="commenting",
    )
    op.drop_column("campaigns", "verify_delay_sec", schema="commenting")
    for name, _ in reversed(_BOOLS):
        op.drop_column("campaigns", name, schema="commenting")
