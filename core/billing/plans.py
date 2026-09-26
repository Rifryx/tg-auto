"""Планы и лимиты — единая точка правды.

Frontend (`frontend/src/shared/plans.ts`) держит зеркальную структуру. Ключи
``FeatureKey`` и значения обязаны совпадать; при расхождении фронт покажет
одно, а сервер откажет — самый обидный сорт бага.

`UNLIMITED = -1` — договорённость: любое отрицательное значение → безлимит.
"""
from __future__ import annotations

from typing import Literal, Union

PlanId = Literal["free", "pro"]
FeatureKey = Literal[
    "accounts_max",
    "personas_max",
    "proxies_max",
    "campaigns_active_max",
    "comments_per_day",
    "channels_watch_max",
    # Модуль shilling
    "shilling_campaigns_active_max",
    "shilling_targets_per_campaign_max",
    "shilling_scenario_steps_max",
    "ai_provider_custom",
    "priority_queue",
    "audit_history_days",
    "support_level",
]

UNLIMITED: int = -1

FeatureValue = Union[int, bool, str]

FEATURE_KEYS: tuple[FeatureKey, ...] = (
    "accounts_max",
    "personas_max",
    "proxies_max",
    "campaigns_active_max",
    "comments_per_day",
    "channels_watch_max",
    "shilling_campaigns_active_max",
    "shilling_targets_per_campaign_max",
    "shilling_scenario_steps_max",
    "ai_provider_custom",
    "priority_queue",
    "audit_history_days",
    "support_level",
)

PLANS: dict[PlanId, dict[FeatureKey, FeatureValue]] = {
    "free": {
        "accounts_max": 1,
        "personas_max": 1,
        "proxies_max": 1,
        "campaigns_active_max": 1,
        "comments_per_day": 20,
        "channels_watch_max": 3,
        "shilling_campaigns_active_max": 1,
        "shilling_targets_per_campaign_max": 10,
        "shilling_scenario_steps_max": 6,
        "ai_provider_custom": False,
        "priority_queue": False,
        "audit_history_days": 3,
        "support_level": "community",
    },
    "pro": {
        "accounts_max": UNLIMITED,
        "personas_max": UNLIMITED,
        "proxies_max": UNLIMITED,
        "campaigns_active_max": UNLIMITED,
        "comments_per_day": 3000,
        "channels_watch_max": UNLIMITED,
        "shilling_campaigns_active_max": UNLIMITED,
        "shilling_targets_per_campaign_max": UNLIMITED,
        "shilling_scenario_steps_max": 30,
        "ai_provider_custom": True,
        "priority_queue": True,
        "audit_history_days": 365,
        "support_level": "priority",
    },
}


def get_plan_limit(plan_id: PlanId, feature: FeatureKey) -> FeatureValue:
    """Значение лимита для (план, ключ). Неизвестный план ⇒ free."""
    return PLANS.get(plan_id, PLANS["free"])[feature]


def is_unlimited(v: FeatureValue) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v < 0
