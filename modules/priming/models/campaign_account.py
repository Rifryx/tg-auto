"""Привязка аккаунта-инициатора к кампании прайминга (spec §4.2).

Один аккаунт может быть активным драйвером **только одной** кампании
прайминга (в отличие от шиллинга). UNIQUE (campaign_id, account_id)
защищает от дублей в пределах кампании; эксклюзивность на уровне
аккаунта обеспечивается сервисным слоем (промпт 2.5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import PRIMING_SCHEMA, Base, CreatedAtMixin
from modules.priming.schemas.enums import PrimingAccountState


class PrimingCampaignAccount(Base, CreatedAtMixin):
    __tablename__ = "campaign_accounts"
    # UniqueConstraint.name используется как есть (naming_convention для uq —
    # ``uq_<table>_<column>``, но с явным именем convention не применяется).
    # CheckConstraint.name префиксуется convention'ом до ``ck_<table>_<name>``.
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "account_id",
            name="uq_campaign_accounts_campaign_id_account_id",
        ),
        CheckConstraint(
            "state IN ("
            + ", ".join(f"'{m.value}'" for m in PrimingAccountState)
            + ")",
            name="state_allowed",
        ),
        CheckConstraint(
            "flood_waits_consecutive >= 0 AND flood_waits_total >= 0",
            name="flood_counters_nonneg",
        ),
        CheckConstraint(
            "primes_today >= 0 AND primes_total >= 0",
            name="prime_counters_nonneg",
        ),
        CheckConstraint(
            "ab_bucket IS NULL OR ab_bucket IN ('a', 'b')",
            name="ab_bucket_allowed",
        ),
        {"schema": PRIMING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{PRIMING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )

    state: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=PrimingAccountState.IDLE.value,
        server_default=PrimingAccountState.IDLE.value,
    )

    flood_waits_consecutive: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    flood_waits_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    primes_today: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    primes_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    last_prime_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_available_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Когда аккаунт впервые начал работать в этой кампании — точка
    # отсчёта warmup-рампы (spec §11.1, prompt 6.1). Ставится при
    # первом ``acquire_next`` и не сдвигается при паузе/возобновлении
    # кампании — прогрев считаем от факта начала работы.
    warmup_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # A/B bucket (prompt 7.3). NULL — bucket не назначен (кампания
    # без A/B); 'a' | 'b' — детерминированный назначенный bucket.
    ab_bucket: Mapped[Optional[str]] = mapped_column(
        String(1), nullable=True,
    )

    # Пресет оформления профиля переехал в общий блок «Аккаунты» —
    # priming больше не хранит эту связку (см. Alembic 0045). Если
    # в будущем понадобится ссылка на конкретный shared-preset, введём
    # новую колонку под уже реальный сервис.
