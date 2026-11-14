"""Реэкспорт ORM-моделей модуля ``mass_reactions``.

Канонические определения — в ``modules/mass_reactions/models``. Тут только
реэкспорт, чтобы ``core.models`` и Alembic (``Base.metadata``) видели таблицы.
"""

from modules.mass_reactions.models import (
    MassReactionCampaign,
    MassReactionCampaignAccount,
    MassReactionCampaignChat,
    MassReactionLog,
)

__all__ = [
    "MassReactionCampaign",
    "MassReactionCampaignAccount",
    "MassReactionCampaignChat",
    "MassReactionLog",
]
