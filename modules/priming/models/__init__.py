"""Реэкспорт ORM-моделей модуля прайминга.

На промпте 1.3 заведены три «горячие» таблицы; ``profile_preset`` /
``anchor_channel`` / ``target_source`` / ``execution_log`` /
``flood_incident`` / ``blacklist`` появятся на промпте 1.4.
"""

from modules.priming.models.campaign import PrimingCampaign
from modules.priming.models.campaign_account import PrimingCampaignAccount
from modules.priming.models.campaign_target import PrimingCampaignTarget

__all__ = [
    "PrimingCampaign",
    "PrimingCampaignAccount",
    "PrimingCampaignTarget",
]
