"""Реэкспорт ORM-моделей модуля ``shilling``.

Канонические определения — в ``modules/shilling/models`` (модуль владеет
своими таблицами). Тут только реэкспорт, чтобы ``core.models`` и Alembic
(``Base.metadata``) видели таблицы без изменения существующих импортов.
"""

from modules.shilling.models import (
    ShillingCampaign,
    ShillingScenario,
    ShillingScenarioRole,
    ShillingScenarioStep,
)

__all__ = [
    "ShillingCampaign",
    "ShillingScenario",
    "ShillingScenarioRole",
    "ShillingScenarioStep",
]
