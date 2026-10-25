"""База знаний «Продукты» для нейрошиллинга.

shilling.products — переиспользуемые описания продукта/сервиса (name, УТП,
ссылка, фичи), чтобы не дублировать их в каждом промпте кампании.
shilling.campaigns.product_id — опциональная связь кампании с продуктом;
при NULL работает старая схема (brand_name/brand_link/topic в самой кампании).

Revision ID: 0064
Revises: 0063
Create Date: 2026-10-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0064"
down_revision: Union[str, None] = "0063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # owner_user_id: Telegram user_id владельца. Поиск продуктов и
        # связывание с кампаниями делаются в контексте этого юзера.
        sa.Column("owner_user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        # Описание — произвольный текст, который попадает в промпт как
        # контекст продвижения (УТП, фичи, цены, кому подходит и т.п.).
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        # Короткое УТП (одной строкой) — отдельно для компактного показа в
        # заголовке реплики, если шаблон его хочет.
        sa.Column("usp", sa.String(length=500), nullable=True),
        # Основной URL продукта/сервиса — его бот может упомянуть текстом.
        sa.Column("website", sa.String(length=500), nullable=True),
        # Ключевые слова через запятую — для будущего авто-подбора продукта
        # под целевой чат (по совпадению тематики).
        sa.Column("tags", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("length(name) >= 1", name="product_name_not_empty"),
        schema="shilling",
    )
    op.create_index(
        "ix_shilling_products_owner",
        "products",
        ["owner_user_id"],
        schema="shilling",
    )

    # Связь кампании с продуктом — опциональная; при удалении продукта
    # кампанию не трогаем (SET NULL), просто откатываемся к ручным
    # brand_name/brand_link/topic самой кампании.
    op.add_column(
        "campaigns",
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        schema="shilling",
    )
    op.create_foreign_key(
        "fk_shilling_campaigns_product",
        "campaigns",
        "products",
        ["product_id"],
        ["id"],
        source_schema="shilling",
        referent_schema="shilling",
        ondelete="SET NULL",
    )

    # Два новых toggle'а на кампании под фичи из конкурентного анализа:
    # - inter_account_reactions_enabled: шаги type=reaction в сценарии +
    #   редкие авто-реакции между ботами в orchestrator;
    # - captcha_solver_enabled: авто-решение капч при входе в закрытые чаты
    #   (требует CAPTCHA_PROVIDER_KEY на сервере).
    # Оба false по умолчанию — старые кампании работают как раньше.
    op.add_column(
        "campaigns",
        sa.Column(
            "inter_account_reactions_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="shilling",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "captcha_solver_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="shilling",
    )


def downgrade() -> None:
    op.drop_column("campaigns", "captcha_solver_enabled", schema="shilling")
    op.drop_column(
        "campaigns", "inter_account_reactions_enabled", schema="shilling"
    )
    op.drop_constraint(
        "fk_shilling_campaigns_product",
        "campaigns",
        type_="foreignkey",
        schema="shilling",
    )
    op.drop_column("campaigns", "product_id", schema="shilling")
    op.drop_index(
        "ix_shilling_products_owner", table_name="products", schema="shilling"
    )
    op.drop_table("products", schema="shilling")
