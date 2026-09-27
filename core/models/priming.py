"""Реэкспорт ORM-моделей модуля ``priming``.

Канонические определения — в ``modules/priming/models``. Тут только
реэкспорт, чтобы ``core.models`` и Alembic (``Base.metadata``) видели
таблицы без изменения существующих импортов.
"""

from modules.priming.models import (
    PrimingCampaign,
    PrimingCampaignAccount,
    PrimingCampaignTarget,
)

__all__ = [
    "PrimingCampaign",
    "PrimingCampaignAccount",
    "PrimingCampaignTarget",
]
