"""Агрегатные схемы для UI: статистика и чеклист готовности к запуску.

См. docs/neuroshilling-spec.md § 4 (эндпоинты /readiness и /stats) и
docs/neuroshilling-ui-ux.md § 5.5 (Sticky launch-панель).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CampaignStats(BaseModel):
    """Агрегат ExecutionLog по статусам за всё время кампании."""

    total: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    replaced: int = 0
    success_rate_percent: int = Field(default=0, ge=0, le=100)


class ReadinessCheck(BaseModel):
    """Единичная строка чеклиста готовности."""

    ok: bool
    label: str  # человекочитаемая метка, напр. «Аккаунты выбраны 4/4»
    reason: str | None = None  # почему не ok, если false


class CampaignReadiness(BaseModel):
    """Полный чеклист + агрегат can_run.

    Порядок полей отражает порядок отображения в StickyLaunchPanel.
    """

    accounts: ReadinessCheck
    scenario: ReadinessCheck
    targets: ReadinessCheck
    can_run: bool  # true, если все три ok


# --- Сухой прогон (docs/neuroshilling-ui-ux.md § 5.6) -----------------------


class DryRunStep(BaseModel):
    """Один шаг симуляции для таймлайна."""

    step_id: int
    account_id: int
    role_name: str
    text: str
    scheduled_at_sec: int  # смещение от старта, сек
    risk_score: str  # low/medium/high/critical/unknown


class DryRunReport(BaseModel):
    job_id: str
    ok: bool
    reason: str | None = None  # почему прогон не удался (валидация/резолв)
    timeline: list[DryRunStep] = []
    total_messages: int = 0
    total_reactions: int = 0
    duration_sec: int = 0
    estimated_tokens: int = 0
