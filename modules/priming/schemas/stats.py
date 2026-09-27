"""Pydantic-схемы агрегатов для UI (spec §13)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from modules.priming.schemas.common import PrimingBaseModel
from modules.priming.schemas.enums import ExecutionOutcome, PrimingAccountState


class ExecutionLogRow(PrimingBaseModel):
    id: int
    campaign_id: int
    account_id: int
    target_id: int
    started_at: datetime
    finished_at: datetime
    outcome: ExecutionOutcome
    error_code: Optional[str] = None
    flood_wait_sec: Optional[int] = None
    trigger_action: str
    latency_ms: int


class CampaignAccountRow(PrimingBaseModel):
    """Строка live-дашборда (§6 UI): один аккаунт кампании."""

    id: int
    account_id: int
    account_username: Optional[str] = None
    state: PrimingAccountState
    primes_today: int
    daily_limit: int
    flood_waits_consecutive: int
    flood_waits_total: int
    next_available_at: Optional[datetime] = None
    last_prime_at: Optional[datetime] = None


class CampaignStats(PrimingBaseModel):
    """Основной набор KPI для экрана «Ход» (§6.1 UI)."""

    campaign_id: int
    primes_total: int = 0
    primes_today: int = 0
    attempts_total: int = 0
    success_rate: float = 0.0        # doля primed от attempts
    privacy_rate: float = 0.0        # доля USER_PRIVACY_RESTRICTED
    flood_rate: float = 0.0          # доля FLOOD_WAIT
    accounts_working: int = 0
    accounts_cooldown: int = 0
    accounts_quarantined: int = 0
    targets_total: int = 0
    targets_pending: int = 0
    targets_primed: int = 0
    targets_failed: int = 0


class CampaignLiveEvent(PrimingBaseModel):
    """Один кадр в WS/SSE-стриме ``/campaigns/{id}/live`` (§6 UI)."""

    kind: str  # "log" | "counter" | "state"
    at: datetime
    payload: dict
