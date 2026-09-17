"""API-эндпоинты Anti-Ban Predictor (этап 11)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from core.repositories.ban_risk import BanRiskRepository
from core.schemas.ban_risk import BanRiskRead

router = APIRouter(prefix="/ban-risk", tags=["ban-risk"], dependencies=[Depends(require_user)])


@router.get("/{account_id}", response_model=BanRiskRead)
def get_ban_risk(account_id: int, session: Session = Depends(get_session)):
    snapshot = BanRiskRepository(session).get(account_id)
    if snapshot is None:
        return BanRiskRead(
            account_id=account_id,
            risk_score=0.0,
            risk_level="low",
        )
    return snapshot


@router.get("/", response_model=list[BanRiskRead])
def list_high_risk(
    min_score: float = 0.5,
    limit: int = 50,
    session: Session = Depends(get_session),
):
    return BanRiskRepository(session).list_high_risk(
        min_score=min_score, limit=limit
    )
