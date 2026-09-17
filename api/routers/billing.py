"""Роутер тарифа: чтение текущего плана + временный dev-endpoint переключения.

* ``GET /billing/plan`` — план пользователя + лимиты + текущее использование.
  Frontend читает и отражает в UI (`useCurrentPlan`, LimitBanner).
* ``POST /billing/plan`` — переключение плана. **Заглушка**: сейчас принимает
  ``plan_id`` напрямую (для локального dev и как точка расширения). Как только
  подключим Telegram Stars / Crypto Bot — этот роут будет вызываться из
  вебхука провайдера, а не из UI.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.services import billing as billing_service

router = APIRouter(prefix="/billing", tags=["billing"])


class SetPlanRequest(BaseModel):
    plan_id: Literal["free", "pro"]
    payment_method: Optional[Literal["stars", "crypto"]] = None


@router.get("/plan")
def get_plan(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return billing_service.get_usage_snapshot(session, user_id)


@router.post("/plan")
def set_plan(
    body: SetPlanRequest,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    billing_service.set_user_plan(session, user_id, body.plan_id, body.payment_method)
    return billing_service.get_usage_snapshot(session, user_id)
