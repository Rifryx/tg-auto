"""ORM-модель кампании модуля НейроШиллинг.

Живёт в схеме Postgres ``shilling`` (создана миграцией 0031_shilling_schema,
таблица — миграцией 0032). Регистрируется в общей ``core.models.base.Base``
metadata, поэтому доступна Alembic и остальному коду.

См. docs/neuroshilling-spec.md § 3.1 «shilling.campaigns».
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import SHILLING_SCHEMA, Base, TimestampMixin


class ShillingCampaign(Base, TimestampMixin):
    """Одна кампания шиллинга — координированный диалог по списку целей."""

    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint(
            "llm_provider IN ('deepseek', 'gemini')",
            name="llm_provider_allowed",
        ),
        CheckConstraint(
            "status IN ('draft', 'ready', 'running', 'paused', 'completed', 'error')",
            name="status_allowed",
        ),
        CheckConstraint(
            "auto_responder IN ('off', 'neuro_dialogs', 'reply_in_chat')",
            name="auto_responder_allowed",
        ),
        CheckConstraint(
            "reply_delay_min_sec >= 0 AND reply_delay_max_sec >= reply_delay_min_sec",
            name="reply_delay_range_valid",
        ),
        CheckConstraint(
            "target_delay_min_sec >= 0 AND target_delay_max_sec >= target_delay_min_sec",
            name="target_delay_range_valid",
        ),
        CheckConstraint(
            "posts_per_target >= 1",
            name="posts_per_target_valid",
        ),
        CheckConstraint(
            "msg_limit_per_hour IS NULL OR msg_limit_per_hour > 0",
            name="msg_limit_per_hour_valid",
        ),
        CheckConstraint(
            "msg_limit_total IS NULL OR msg_limit_total > 0",
            name="msg_limit_total_valid",
        ),
        {"schema": SHILLING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)

    # ── Продвижение: бренд/ссылка (упоминается в репликах текстом) ──────
    brand_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    brand_link: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    topic: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── LLM и рерайтинг ─────────────────────────────────────────────────
    llm_provider: Mapped[str] = mapped_column(
        String, nullable=False, default="deepseek", server_default="deepseek"
    )
    # unique_messages: перед постингом ИИ уникализирует базовый текст реплики
    # (нужно, чтобы одинаковый сценарий не выглядел скопипасченным).
    unique_messages: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # use_chat_context: подтягиваем контекст поста/чата в промпт рерайта.
    use_chat_context: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # ── Тайминги ────────────────────────────────────────────────────────
    reply_delay_min_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    reply_delay_max_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15, server_default="15"
    )
    target_delay_min_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=600, server_default="600"
    )
    target_delay_max_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1800, server_default="1800"
    )
    posts_per_target: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    # ── Сценарий и медиа ────────────────────────────────────────────────
    # scenario_id — обратная FK на shilling.scenarios (у кампании один активный
    # сценарий). При удалении сценария оставляем кампанию, но чистим ссылку.
    scenario_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.scenarios.id", ondelete="SET NULL"),
        nullable=True,
    )
    media_asset_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Автоответчик и резерв ───────────────────────────────────────────
    auto_responder: Mapped[str] = mapped_column(
        String, nullable=False, default="off", server_default="off"
    )
    reserve_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # ── Лимиты на аккаунт ───────────────────────────────────────────────
    msg_limit_per_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    msg_limit_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Runtime-статус ──────────────────────────────────────────────────
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="draft", server_default="draft"
    )
