"""Pydantic-схемы модуля прайминга.

- ``enums.py``  — единый реестр enum'ов (промпт 1.2).
- ``common.py`` — базовые контейнеры (Pagination / Page / TimeRange / Error).

Доменные схемы (кампания, цели, пресеты, статистика) появляются
на промпте 1.6 — см. ``docs/priming-prompts.md``.
"""

from modules.priming.schemas.common import (
    ErrorEnvelope,
    Page,
    Pagination,
    PrimingBaseModel,
    TimeRange,
)
from modules.priming.schemas.enums import (
    AnchorChannelState,
    BlacklistReason,
    ExecutionOutcome,
    HumanizerMode,
    ParserSourceKind,
    PrimingAccountState,
    PrimingCampaignStatus,
    PrimingMode,
    TargetLastSeen,
    TargetStatus,
    TriggerAction,
    WarmupProfile,
    all_enums,
    can_target_status_transition,
    target_status_allowed_transitions,
)

__all__ = [
    "ErrorEnvelope",
    "Page",
    "Pagination",
    "PrimingBaseModel",
    "TimeRange",
    "AnchorChannelState",
    "BlacklistReason",
    "ExecutionOutcome",
    "HumanizerMode",
    "ParserSourceKind",
    "PrimingAccountState",
    "PrimingCampaignStatus",
    "PrimingMode",
    "TargetLastSeen",
    "TargetStatus",
    "TriggerAction",
    "WarmupProfile",
    "all_enums",
    "can_target_status_transition",
    "target_status_allowed_transitions",
]
