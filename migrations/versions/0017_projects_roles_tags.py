"""Проекты, роли, теги для аккаунтов (этап 2).

Раньше был только контейнер «commenting.campaigns» через
``accounts.assigned_container_*``. Теперь появляется отдельная категория
пользовательской группировки — проекты (папки), плюс роль аккаунта в
проекте и свободные теги для фильтрации.

Отличие от campaigns:
* Кампания = рабочий контейнер модуля (эксклюзивно занимает аккаунт).
* Проект = ярлык владельца («все под один запуск», «резерв», …); аккаунт
  может быть в проекте И одновременно в кампании.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_projects_user_name"),
    )
    op.create_index("ix_projects_user", "projects", ["user_id"])

    # accounts: project_id (FK), role, tags TEXT[]
    op.add_column(
        "accounts",
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "role",
            sa.String(),
            nullable=True,
        ),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "tags",
            sa.dialects.postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
    )
    op.create_check_constraint(
        "role_allowed",
        "accounts",
        "role IS NULL OR role IN ('main', 'support', 'warmup', 'burner')",
    )
    op.create_index("ix_accounts_project_id", "accounts", ["project_id"])
    op.create_index("ix_accounts_role", "accounts", ["role"])
    # GIN-индекс на tags — для быстрых фильтров ?tag=vip.
    op.create_index(
        "ix_accounts_tags_gin", "accounts", ["tags"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_accounts_tags_gin", table_name="accounts")
    op.drop_index("ix_accounts_role", table_name="accounts")
    op.drop_index("ix_accounts_project_id", table_name="accounts")
    op.drop_constraint("role_allowed", "accounts", type_="check")
    op.drop_column("accounts", "tags")
    op.drop_column("accounts", "role")
    op.drop_column("accounts", "project_id")
    op.drop_index("ix_projects_user", table_name="projects")
    op.drop_table("projects")
