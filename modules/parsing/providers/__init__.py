"""Провайдеры каталога сообществ (Discovery, этап 3).

Реестр по имени. Сейчас: telemetrio. Задел под tgstat / apify-обёртку.
"""

from modules.parsing.providers.base import (
    CatalogProvider,
    CatalogProviderError,
    CatalogQuery,
    CommunityCandidate,
)
from modules.parsing.providers.telemetrio import TelemetrioProvider


def get_provider(name: str = "telemetrio", **kwargs) -> CatalogProvider:
    if name == "telemetrio":
        return TelemetrioProvider(**kwargs)
    raise CatalogProviderError(f"unknown catalog provider: {name!r}")


__all__ = [
    "CatalogProvider",
    "CatalogProviderError",
    "CatalogQuery",
    "CommunityCandidate",
    "TelemetrioProvider",
    "get_provider",
]
