"""FastAPI-зависимость: проверка лимита текущего плана.

Используется как ``Depends(enforce_limit("accounts_max"))`` рядом с
``Depends(require_user)`` в create-роутах. При превышении отдаёт HTTP 402
Payment Required с телом ``{feature, used, limit, plan_id, reason}`` — фронт
по этому телу показывает CTA перехода на тариф.
"""
from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.services import billing as billing_service
from core.billing.plans import FeatureKey, get_plan_limit


def enforce_limit(feature: FeatureKey) -> Callable[..., None]:
    """Фабрика зависимости для одного FeatureKey."""

    def _dep(
        user_id: str = Depends(require_user),
        session: Session = Depends(get_session),
    ) -> None:
        try:
            billing_service.check_limit(session, user_id, feature)
        except billing_service.LimitExceededError as exc:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "reason": "limit_exceeded",
                    "feature": exc.feature,
                    "used": exc.used,
                    "limit": exc.limit,
                    "plan_id": exc.plan_id,
                },
            ) from exc

    return _dep


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def require_feature(feature: FeatureKey) -> Callable[..., None]:
    """FastAPI-зависимость: boolean-фича должна быть True для плана.

    Ставится router-wide (``APIRouter(dependencies=[require_feature(...)])``).
    Пропускает GET/HEAD/OPTIONS — UI должен уметь показать экран с
    пейволл-капсулой, а не пустоту; блокирует любые write-методы 402.
    """

    def _dep(
        request: Request,
        user_id: str = Depends(require_user),
        session: Session = Depends(get_session),
    ) -> None:
        if request.method in _SAFE_METHODS:
            return
        plan_id = billing_service.get_user_plan(session, user_id)
        value = get_plan_limit(plan_id, feature)
        if not bool(value):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "reason": "feature_locked",
                    "feature": feature,
                    "plan_id": plan_id,
                },
            )

    return _dep
