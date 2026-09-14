"""campaign.persona_id

Персона по умолчанию для кампании (папки аккаунтов): применяется к аккаунтам без
собственной персоны. FK на personas с ON DELETE SET NULL.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "commenting"


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("persona_id", sa.BigInteger(), nullable=True),
        schema=_SCHEMA,
    )
    op.create_foreign_key(
        "fk_campaigns_persona_id_personas",
        "campaigns",
        "personas",
        ["persona_id"],
        ["id"],
        source_schema=_SCHEMA,
        referent_schema="public",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_campaigns_persona_id_personas",
        "campaigns",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("campaigns", "persona_id", schema=_SCHEMA)
