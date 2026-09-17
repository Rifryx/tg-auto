"""Тарифы и лимиты — серверная сторона.

Ключевой инвариант: планы и значения лимитов лежат ТОЛЬКО в
:mod:`core.billing.plans`. Фронт (`frontend/src/shared/plans.ts`) и бэкенд
обязаны использовать одни и те же ключи ``FeatureKey`` и совпадающие значения.
Изменил цифру здесь — измени и там; хочешь новую фичу — добавь ключ
одновременно в обе стороны.
"""

from core.billing.plans import (
    FEATURE_KEYS,
    PLANS,
    UNLIMITED,
    FeatureKey,
    PlanId,
    get_plan_limit,
)

__all__ = [
    "FEATURE_KEYS",
    "PLANS",
    "UNLIMITED",
    "FeatureKey",
    "PlanId",
    "get_plan_limit",
]
