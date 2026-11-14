"""Репозитории модуля масс-реакций — единственная точка SQL."""

from modules.mass_reactions.repositories.campaign import CampaignRepository
from modules.mass_reactions.repositories.campaign_account import (
    CampaignAccountRepository,
)
from modules.mass_reactions.repositories.campaign_chat import CampaignChatRepository
from modules.mass_reactions.repositories.log import LogRepository

__all__ = [
    "CampaignRepository",
    "CampaignAccountRepository",
    "CampaignChatRepository",
    "LogRepository",
]
