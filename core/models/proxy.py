from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, TimestampMixin


class Proxy(Base, TimestampMixin):
    __tablename__ = "proxies"
    __table_args__ = (
        CheckConstraint(
            "type IN ('socks5', 'http')",
            name="type_allowed",
        ),
        CheckConstraint(
            "status IN ('alive', 'dead', 'unchecked')",
            name="status_allowed",
        ),
        Index("ix_proxies_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    host: Mapped[str] = mapped_column(String, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    login: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    password_enc: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    geo: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="unchecked", server_default="unchecked"
    )
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
