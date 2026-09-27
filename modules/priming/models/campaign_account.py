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

    # FK на priming.profile_presets появится в миграции 0041 (промпт 1.4),
    # когда таблица пресетов будет заведена. Здесь колонка объявлена
    # без FK-констрейнта, чтобы миграция 1.3 не ссылалась на ещё
    # несуществующую таблицу; ORM-констрейнт будет добавлен вместе с
    # таблицей.
    profile_preset_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
