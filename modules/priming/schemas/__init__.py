"""Pydantic-схемы модуля прайминга.

- ``enums.py``           — единый реестр enum'ов (промпт 1.2).
- ``common.py``          — базовые контейнеры (Pagination / Page / TimeRange / Error).
- ``campaign.py``        — Create/Update/Read кампании (+ Counters).
- ``target.py``          — цели (Create/Import/Read/BulkBlacklist).
- ``profile_preset.py``  — POC-пресеты (Create/Update/Read/ApplyPreset).
- ``anchor_channel.py``  — anchor-каналы (Create/Update/Read).
- ``parser.py``          — запросы к парсеру и статусы job'ов.
- ``stats.py``           — агрегаты и live-events для UI.
"""

from modules.priming.schemas.anchor_channel import (
    AnchorChannelCreate,
    AnchorChannelRead,
    AnchorChannelUpdate,
)
from modules.priming.schemas.campaign import (
    PrimingCampaignCounters,
    PrimingCampaignCreate,
    PrimingCampaignRead,
    PrimingCampaignUpdate,
)
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
from modules.priming.schemas.parser import (
    ChatMembersParserParams,
    ChatMessagesParserParams,
    ParserJobStatus,
    ParserRunRequest,
    TargetSourceRead,
)
from modules.priming.schemas.stats import (
    CampaignAccountRow,
    CampaignLiveEvent,
    CampaignStats,
    ExecutionLogRow,
)
from modules.priming.schemas.target import (
    PrimingTargetBulkBlacklist,
    PrimingTargetCreate,
    PrimingTargetImport,
    PrimingTargetRead,
)

__all__ = [
    # common
    "ErrorEnvelope",
    "Page",
    "Pagination",
    "PrimingBaseModel",
    "TimeRange",
    # enums
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
    # campaign
    "PrimingCampaignCreate",
    "PrimingCampaignUpdate",
    "PrimingCampaignRead",
    "PrimingCampaignCounters",
    # target
    "PrimingTargetCreate",
    "PrimingTargetImport",
    "PrimingTargetRead",
    "PrimingTargetBulkBlacklist",
    # anchor
    "AnchorChannelCreate",
    "AnchorChannelUpdate",
    "AnchorChannelRead",
    # parser
    "ChatMessagesParserParams",
    "ChatMembersParserParams",
    "ParserRunRequest",
    "ParserJobStatus",
    "TargetSourceRead",
    # stats
    "ExecutionLogRow",
    "CampaignAccountRow",
    "CampaignStats",
    "CampaignLiveEvent",
]
