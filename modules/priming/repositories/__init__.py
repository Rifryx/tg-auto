"""Репозитории модуля прайминга (промпт 1.5)."""

from modules.priming.repositories.anchor_channel import AnchorChannelRepository
from modules.priming.repositories.blacklist import BlacklistRepository
from modules.priming.repositories.campaign import CampaignRepository
from modules.priming.repositories.campaign_account import (
    CampaignAccountRepository,
)
from modules.priming.repositories.campaign_target import (
    CampaignTargetRepository,
)
from modules.priming.repositories.execution_log import ExecutionLogRepository
from modules.priming.repositories.flood_incident import (
    FloodIncidentRepository,
)
from modules.priming.repositories.target_source import (
    TargetSourceRepository,
)

__all__ = [
    "AnchorChannelRepository",
    "BlacklistRepository",
    "CampaignAccountRepository",
    "CampaignRepository",
    "CampaignTargetRepository",
    "ExecutionLogRepository",
    "FloodIncidentRepository",
    "TargetSourceRepository",
]
