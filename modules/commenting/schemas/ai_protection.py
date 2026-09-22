"""Read-only статус ИИ-защиты аккаунтов (§ Этап 5).

Не отдельный модуль — обёртка над уже работающими фоновыми задачами
(warming maintenance / anti-ban predictor / health check / autopilot),
чтобы UI мог показать «защита активна» вместо paywall'а конкурента.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

FeatureStatus = Literal["active", "degraded", "off"]


class AiProtectionFeature(BaseModel):
    key: str
    label: str
    description: str
    status: FeatureStatus


class AccountRiskBucket(BaseModel):
    """Сколько аккаунтов сейчас в каждом бакете риска бана."""

    low: int = 0
    medium: int = 0
    high: int = 0
    critical: int = 0
    unknown: int = 0  # ещё не считался


class AiProtectionStatus(BaseModel):
    active: bool
    features: list[AiProtectionFeature]
    accounts_by_risk: AccountRiskBucket
    total_accounts: int
