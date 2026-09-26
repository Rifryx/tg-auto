"""Сервис лимитов: получить план пользователя, проверить лимит.

Используется как FastAPI-зависимость через фабрику ``enforce_limit``.
При превышении кидает :class:`LimitExceededError`, которую роутинг маппит
в HTTP 402 Payment Required с подробностями (feature/used/limit/plan_id) —
фронт по этим полям показывает CTA перехода на тариф.

Счётчики использования читаются напрямую из БД по каждому ключу. Это чуть
дороже, чем считать при создании, зато точно и не зависит от кэша фронта.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.billing.plans import (
    FEATURE_KEYS,
    FeatureKey,
    FeatureValue,
    PlanId,
    get_plan_limit,
    is_unlimited,
)
from core.models.account import Account
from core.models.persona import Persona
from core.models.proxy import Proxy
from core.repositories.subscription import SubscriptionRepository
from modules.commenting.models.campaign import Campaign
from modules.shilling.models import ShillingCampaign


# ------------------------------ ошибки ---------------------------------------


@dataclass(frozen=True)
class LimitExceededError(Exception):
    feature: FeatureKey
    used: int
    limit: int
    plan_id: PlanId

    def __str__(self) -> str:  # для логов
        return (
            f"limit exceeded: feature={self.feature} used={self.used} "
            f"limit={self.limit} plan={self.plan_id}"
        )


# ------------------------------ план -----------------------------------------


def get_user_plan(session: Session, user_id: str) -> PlanId:
    """План пользователя (Free по умолчанию, если записи нет)."""
    sub = SubscriptionRepository(session).get(user_id)
    if sub is None:
        return "free"
    return "pro" if sub.plan_id == "pro" else "free"


def set_user_plan(
    session: Session, user_id: str, plan_id: PlanId, payment_method: str | None = None
) -> None:
    SubscriptionRepository(session).upsert(user_id, plan_id, payment_method)
    session.commit()


# ------------------------------ счётчики -------------------------------------
#
# Счётчик — это (session) -> int. Держим их в одном месте и добавляем строку
# при появлении новой фичи. Ключ — тот же FeatureKey, значения совпадают
# с фронтовыми USAGE_HOOKS.


def _count_accounts(session: Session) -> int:
    return int(
        session.execute(select(func.count()).select_from(Account)).scalar_one()
    )


def _count_personas(session: Session) -> int:
    return int(
        session.execute(select(func.count()).select_from(Persona)).scalar_one()
    )


def _count_proxies(session: Session) -> int:
    return int(session.execute(select(func.count()).select_from(Proxy)).scalar_one())


def _count_active_campaigns(session: Session) -> int:
    # На модели кампании нет статуса «завершена»/«архив» — есть только
    # ``enabled``. Считаем любые созданные кампании: одна кампания = один слот.
    return int(
        session.execute(select(func.count()).select_from(Campaign)).scalar_one()
    )


def _count_shilling_campaigns(session: Session) -> int:
    # Одна кампания шиллинга = один слот (статуса «архив» у модели нет).
    return int(
        session.execute(select(func.count()).select_from(ShillingCampaign)).scalar_one()
    )


USAGE_COUNTERS: dict[FeatureKey, Callable[[Session], int]] = {
    "accounts_max": _count_accounts,
    "personas_max": _count_personas,
    "proxies_max": _count_proxies,
    "campaigns_active_max": _count_active_campaigns,
    "shilling_campaigns_active_max": _count_shilling_campaigns,
}


# ------------------------------ проверка -------------------------------------


def _to_int_limit(v: FeatureValue) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        return 0
    return v


def get_usage_snapshot(session: Session, user_id: str) -> dict[str, object]:
    """Слепок для ``GET /billing/plan``: план, лимиты, текущее использование."""
    plan_id = get_user_plan(session, user_id)
    limits: dict[str, FeatureValue] = {k: get_plan_limit(plan_id, k) for k in FEATURE_KEYS}
    usage: dict[str, int] = {k: fn(session) for k, fn in USAGE_COUNTERS.items()}
    return {"plan_id": plan_id, "limits": limits, "usage": usage}


def _bypass_enabled() -> bool:
    """Тестовый обход гейта.

    Единственная причина существования — pytest-набор, где один тест создаёт
    много сущностей подряд под dev-user'ом. В обычном dev-режиме гейт активен,
    чтобы UI-поведение можно было проверить вручную.
    """
    return os.getenv("BILLING_BYPASS_LIMITS") == "1"


def check_limit(session: Session, user_id: str, feature: FeatureKey) -> None:
    """Проверяет, что создание ЕЩЁ ОДНОЙ единицы ресурса ``feature`` разрешено.

    Кидает :class:`LimitExceededError`, если лимит достигнут.
    Для не-числовых лимитов (флаги) — просто возвращает управление, гейт по ним
    делает вызывающий код (например, «свой ключ модели» — не через create-роут).
    """
    if _bypass_enabled():
        return
    counter = USAGE_COUNTERS.get(feature)
    if counter is None:
        return  # у этой фичи нет счётчика создания — не наша забота
    plan_id = get_user_plan(session, user_id)
    limit_value = get_plan_limit(plan_id, feature)
    if is_unlimited(limit_value):
        return
    limit_int = _to_int_limit(limit_value)
    used = counter(session)
    if used >= limit_int:
        raise LimitExceededError(
            feature=feature, used=used, limit=limit_int, plan_id=plan_id
        )


def check_count_limit(
    session: Session, user_id: str, feature: FeatureKey, current_count: int
) -> None:
    """Проверка per-parent лимита (цели на кампанию, шаги на сценарий).

    В отличие от :func:`check_limit`, счётчик здесь не глобальный, а передаётся
    вызывающим (у зависимости ``enforce_limit`` нет доступа к path-параметру
    родителя). Логика та же: достигли лимита → ``LimitExceededError`` → 402.
    """
    if _bypass_enabled():
        return
    plan_id = get_user_plan(session, user_id)
    limit_value = get_plan_limit(plan_id, feature)
    if is_unlimited(limit_value):
        return
    limit_int = _to_int_limit(limit_value)
    if current_count >= limit_int:
        raise LimitExceededError(
            feature=feature, used=current_count, limit=limit_int, plan_id=plan_id
        )
