from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class BanRiskRead(BaseModel):
    account_id: int
    risk_score: float
    risk_level: str
    previous_risk_score: Optional[float] = None
    features: dict[str, Any] = {}
    contributions: list[dict[str, Any]] = []
    computed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
