"""Media store для больших payload'ов Stories (этап 9, backlog #1).

Раньше `publish_story.payload.media_b64` — картинка base64 в JSONB. Для
1080×1920 фото это ~1–2 МБ на job; для видео и подавно нереально. Таблица
``media_assets`` держит бинарь один раз, а payload ссылается на media_asset_id.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("mime", sa.String(), nullable=False),
        sa.Column("bytes", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Уникальный sha256 в разрезе user_id — одну и ту же картинку не
        # держим дважды. Разные user_id могут иметь одинаковый sha (изоляция).
        sa.UniqueConstraint("user_id", "sha256", name="uq_media_user_sha"),
    )
    op.create_index("ix_media_assets_user", "media_assets", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_media_assets_user", table_name="media_assets")
    op.drop_table("media_assets")
