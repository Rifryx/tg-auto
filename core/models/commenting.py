"""Реэкспорт ORM-моделей модуля ``commenting``.

Канонические определения перенесены в ``modules/commenting/models`` (модуль —
владелец своих таблиц). Здесь остаётся только реэкспорт, чтобы ``core.models``
и Alembic (``Base.metadata``) продолжали видеть эти таблицы без изменения
существующих импортов.
"""

from modules.commenting.models import (
    Campaign,
    CampaignAccount,
    CommentLog,
    MonitoredChannel,
)

__all__ = ["Campaign", "CampaignAccount", "CommentLog", "MonitoredChannel"]
