from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, TimestampMixin


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'warming', 'pool', 'assigned', "
            "'cooldown', 'retired', 'banned')",
            name="status_allowed",
        ),
        CheckConstraint(
            "warming_profile IN ('minimal', 'medium', 'dense')",
            name="warming_profile_allowed",
        ),
        CheckConstraint(
            "(assigned_container_type IS NULL) = (assigned_container_id IS NULL)",
            name="assignment_pair_consistent",
        ),
        Index("ix_accounts_status", "status"),
        Index("ix_accounts_proxy_id", "proxy_id"),
        Index("ix_accounts_persona_id", "persona_id"),
        Index(
            "ix_accounts_assigned_container",
            "assigned_container_type",
            "assigned_container_id",
        ),
        Index(
            "ix_accounts_pool_warming_profile",
            "status",
            "warming_profile",
            postgresql_where=text("status = 'pool'"),
        ),
        Index(
            "ix_accounts_cooldown_until",
            "cooldown_until",
            postgresql_where=text("status = 'cooldown'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    phone: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    first_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    session_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    proxy_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("proxies.id", ondelete="SET NULL"), nullable=True
    )
    persona_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("personas.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String, nullable=False, default="created", server_default="created"
    )
    previous_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    assigned_container_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    assigned_container_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    warming_profile: Mapped[str] = mapped_column(
        String, nullable=False, default="medium", server_default="medium"
    )
    warming_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cooldown_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Фингерпринт устройства. Иммутабельность после стадии `created` обеспечивается
    # сервисным слоем (репозиторием), не БД.
    device_model: Mapped[str] = mapped_column(String, nullable=False)
    system_version: Mapped[str] = mapped_column(String, nullable=False)
    app_version: Mapped[str] = mapped_column(String, nullable=False)
    lang_code: Mapped[str] = mapped_column(String, nullable=False)
    system_lang_code: Mapped[str] = mapped_column(String, nullable=False)

    # Служебный JSONB для эфемерного состояния (напр. phone_code_hash логин-флоу).
    # Не для доменных полей — те выносятся в отдельные колонки.
    meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # 2FA-пароль (шифруется тем же ``core.crypto.encrypt_password``, что и
    # пароли прокси). Хранится, чтобы worker мог логиниться после установки
    # и/или менять/снимать пароль bulk-операцией. Plaintext в БД не попадает
    # ни на одном пути (bulk-job API шифрует до записи).
    two_factor_password_enc: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    two_factor_hint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
