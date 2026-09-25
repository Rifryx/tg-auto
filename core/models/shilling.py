"""Реэкспорт ORM-моделей модуля ``shilling``.

Канонические определения — в ``modules/shilling/models`` (модуль владеет
своими таблицами). Тут только реэкспорт, чтобы ``core.models`` и Alembic
(``Base.metadata``) видели таблицы без изменения существующих импортов.
"""

from modules.shilling.models import (
    ShillingBlacklist,
    ShillingCampaign,
    ShillingCampaignAccount,
    ShillingExecutionLog,
    ShillingScenario,
    ShillingScenarioRole,
    ShillingScenarioStep,
    ShillingTarget,
)

__all__ = [
    "ShillingBlacklist",
    "ShillingCampaign",
    "ShillingCampaignAccount",
    "ShillingExecutionLog",
    "ShillingScenario",
    "ShillingScenarioRole",
    "ShillingScenarioStep",
    "ShillingTarget",
]
