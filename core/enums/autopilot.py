"""Enums для Autopilot (этап 12)."""

from __future__ import annotations

from enum import Enum


class GoalType(str, Enum):
    """Тип цели автопилота."""

    MAINTAIN_POOL_SIZE = "maintain_pool_size"
    KEEP_LOW_RISK = "keep_low_risk"
    WARMUP_PIPELINE = "warmup_pipeline"


class AutopilotActionType(str, Enum):
    """Тип действия, которое автопилот запланировал/выполнил."""

    START_WARMING = "start_warming"
    RETIRE_RISKY = "retire_risky"
    THROTTLE = "throttle"
    NOOP = "noop"


class AutopilotActionStatus(str, Enum):
    """Статус запланированного действия."""

    PLANNED = "planned"
    EXECUTED = "executed"
    FAILED = "failed"
    SKIPPED = "skipped"
