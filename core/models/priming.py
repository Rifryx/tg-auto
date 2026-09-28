"""Реэкспорт ORM-моделей модуля ``priming``.

Канонические определения — в ``modules/priming/models``. Тут только
реэкспорт, чтобы ``core.models`` и Alembic (``Base.metadata``) видели
таблицы без изменения существующих импортов.
"""

from modules.priming.models import (
    PrimingAnchorChannel,
    PrimingBlacklist,
    PrimingCampaign,
    PrimingCampaignAccount,
    PrimingCampaignTarget,
    PrimingExecutionLog,
    PrimingFloodIncident,
    PrimingTargetSource,
)

__all__ = [
    "PrimingAnchorChannel",
    "PrimingBlacklist",
    "PrimingCampaign",
    "PrimingCampaignAccount",
    "PrimingCampaignTarget",
    "PrimingExecutionLog",
    "PrimingFloodIncident",
    "PrimingTargetSource",
]
