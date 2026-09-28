"""priming: убрать profile_presets — переезд в общий блок «Аккаунты»

Пользователь: оформление профилей — общая инфраструктура (уже есть
worker/profiles/apply.py + bulk-действия apply_profile / _pool /
generate_and_apply_profile, и AccountDetailScreen редактирует профиль).
Priming.profile_presets и campaign_accounts.profile_preset_id
удаляются — прайминг больше не владеет пресетами оформления.

При необходимости связать campaign_account с общим пресетом — введём
новую колонку когда общий модуль формально появится; сейчас хватает
работы через bulk-actions на аккаунтах.

Revision ID: 0045
Revises: 0044
Create Date: 2026-09-27
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0045"
down_revision: Union[str, None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIMING = "priming"


def upgrade() -> None:
    op.drop_constraint(
        "fk_campaign_accounts_profile_preset_id_profile_presets",
        "campaign_accounts",
        type_="foreignkey",
        schema=PRIMING,
    )
    op.drop_column(
        "campaign_accounts", "profile_preset_id", schema=PRIMING,
    )
    op.drop_index(
        "ix_profile_presets_owner",
        table_name="profile_presets",
        schema=PRIMING,
    )
    op.drop_table("profile_presets", schema=PRIMING)


def downgrade() -> None:
    """Восстанавливаем 0041-состояние (без данных)."""
    import sqlalchemy as sa

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
        schema=PRIMING,
    )
    op.create_index(
        "ix_profile_presets_owner", "profile_presets",
        ["owner_user_id"], schema=PRIMING,
    )
    op.add_column(
        "campaign_accounts",
        sa.Column("profile_preset_id", sa.BigInteger(), nullable=True),
        schema=PRIMING,
    )
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
