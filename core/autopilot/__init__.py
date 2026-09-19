"""Autopilot core: чистая логика планирования (этап 12)."""

from core.autopilot.planner import (
    FleetState,
    PlannedAction,
    plan,
)

__all__ = ["FleetState", "PlannedAction", "plan"]
