"""Биллинг MVP: конфиг цены, акции, леджер платежей, скрытия шторки.

Новые таблицы в схеме public:
* ``pricing_config``  — singleton (id=1): базовая цена USDT/Stars + период (дни).
* ``promotions``      — временны́е акции (percent/fixed) поверх базовой цены.
* ``payments``        — леджер платежей Stars/Crypto с идемпотентным применением.
* ``promo_dismissals``— отметки «пользователь скрыл шторку акции».

Revision ID: 0054
Revises: 0053
Create Date: 2026-10-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: Union[str, None] = "0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- pricing_config (singleton) ---
    op.create_table(
        "pricing_config",
        sa.Column("id", sa.SmallInteger(), primary_key=True, autoincrement=False),
        sa.Column("price_usdt", sa.Numeric(12, 2), nullable=False),
        sa.Column("price_stars", sa.Integer(), nullable=False),
        sa.Column("period_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 1", name="ck_pricing_config_singleton"),
        sa.CheckConstraint("price_usdt >= 0", name="ck_pricing_config_price_usdt_nonneg"),
        sa.CheckConstraint("price_stars >= 0", name="ck_pricing_config_price_stars_nonneg"),
        sa.CheckConstraint("period_days > 0", name="ck_pricing_config_period_days_positive"),
    )
    # Сид: текущие значения из фронта ($19 / 950⭐ / 30 дней).
    op.bulk_insert(
        sa.table(
            "pricing_config",
            sa.column("id", sa.SmallInteger),
            sa.column("price_usdt", sa.Numeric(12, 2)),
            sa.column("price_stars", sa.Integer),
            sa.column("period_days", sa.Integer),
        ),
        [{"id": 1, "price_usdt": 19.00, "price_stars": 950, "period_days": 30}],
    )

    # --- promotions ---
    op.create_table(
        "promotions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("percent_off", sa.Integer(), nullable=True),
        sa.Column("promo_price_usdt", sa.Numeric(12, 2), nullable=True),
        sa.Column("promo_price_stars", sa.Integer(), nullable=True),
        sa.Column("badge_variant", sa.String(), nullable=False, server_default="gold"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.String(), nullable=True),
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
        sa.CheckConstraint("kind IN ('percent', 'fixed')", name="ck_promotions_kind_allowed"),
        sa.CheckConstraint(
            "(kind = 'percent' AND percent_off IS NOT NULL "
            "AND percent_off BETWEEN 1 AND 95) "
            "OR (kind = 'fixed' AND promo_price_usdt IS NOT NULL "
            "AND promo_price_stars IS NOT NULL)",
            name="ck_promotions_kind_fields_consistent",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_promotions_window_valid"),
    )
    op.create_index(
        "ix_promotions_window", "promotions", ["enabled", "starts_at", "ends_at"]
    )

    # --- payments (леджер) ---
    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_invoice_id", sa.String(), nullable=True),
        sa.Column("pay_url", sa.String(), nullable=True),
        sa.Column("payload", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False, server_default="pro"),
        sa.Column("period_days", sa.Integer(), nullable=False),
        sa.Column("promo_id", sa.BigInteger(), nullable=True),
        sa.Column("price_usdt", sa.Numeric(12, 2), nullable=False),
        sa.Column("price_stars", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider IN ('stars', 'crypto')", name="ck_payments_provider_allowed"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'paid', 'expired', 'failed')",
            name="ck_payments_status_allowed",
        ),
        sa.UniqueConstraint("payload", name="uq_payments_payload"),
    )
    op.create_index(
        "uq_payments_provider_invoice",
        "payments",
        ["provider", "provider_invoice_id"],
        unique=True,
        postgresql_where=sa.text("provider_invoice_id IS NOT NULL"),
    )
    op.create_index(
        "ix_payments_status_provider", "payments", ["status", "provider"]
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])

    # --- promo_dismissals ---
    op.create_table(
        "promo_dismissals",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("promo_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "dismissed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("promo_dismissals")
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.drop_index("ix_payments_status_provider", table_name="payments")
    op.drop_index("uq_payments_provider_invoice", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_promotions_window", table_name="promotions")
    op.drop_table("promotions")
    op.drop_table("pricing_config")
