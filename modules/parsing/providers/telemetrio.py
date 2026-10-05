"""Провайдер каталога Telemetr.io (Discovery, этап 3).

API: base ``https://api.tlmtr.io``, авторизация заголовком ``x-api-key``.
Подтверждённые эндпоинты:
* ``GET /v1/usage/info``               — квота/тип ключа (не тратит квоту);
* ``GET /v1/channels/search?term=&limit=`` — поиск по названию/описанию;
* ``GET /v1/channel/info?internal_id=`` — инфо по каналу;
* ``GET /v1/catalog/search``           — каталог с фильтрами (category, subscribers,
  views, ER, country, language, privacy, verification; сорт members/growth/...).

Точные имена query-параметров ``/v1/catalog/search`` и поля ответа
подтверждаются ``scripts/telemetrio_probe.py`` (нужен ключ). Маппинг параметров
вынесен в ``_CATALOG_PARAMS`` — правится одним местом после probe.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from core.config import get_settings
from modules.parsing.providers.base import (
    CatalogProvider,
    CatalogProviderError,
    CatalogQuery,
    CommunityCandidate,
)

BASE_URL = "https://api.tlmtr.io"

# Маппинг наших полей CatalogQuery → query-параметры /v1/catalog/search.
# ВНИМАНИЕ: имена предварительные (docs отдаёт схему только с ключом) — сверить
# probe-скриптом и при необходимости поправить здесь.
_CATALOG_PARAMS: dict[str, str] = {
    "term": "term",
    "category": "category",
    "language": "language",
    "country": "country",
    "min_participants": "subscribers_from",
    "max_participants": "subscribers_to",
    "sort": "sort",
    "limit": "limit",
}


class TelemetrioProvider:
    name = "telemetrio"

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        client: Optional[httpx.AsyncClient] = None,
        base_url: str = BASE_URL,
    ) -> None:
        self._api_key = api_key if api_key is not None else get_settings().telemetrio_api_key
        self._client = client
        self._base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise CatalogProviderError(
                "telemetrio: нет API-ключа (settings.telemetrio_api_key / TELEMETRIO_API_KEY)"
            )
        return {"x-api-key": self._api_key, "Accept": "application/json"}

    async def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        own = self._client is None
        client = self._client or httpx.AsyncClient(timeout=20.0)
        try:
            resp = await client.get(
                f"{self._base_url}{path}", params=params, headers=self._headers()
            )
            if resp.status_code == 401:
                raise CatalogProviderError("telemetrio: 401 — неверный/просроченный ключ")
            if resp.status_code == 429:
                raise CatalogProviderError("telemetrio: 429 — исчерпана квота")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise CatalogProviderError(f"telemetrio: сетевая ошибка: {exc}") from exc
        finally:
            if own:
                await client.aclose()

    async def check(self) -> dict:
        data = await self._get("/v1/usage/info")
        return data if isinstance(data, dict) else {"raw": data}

    async def search(self, query: CatalogQuery) -> list[CommunityCandidate]:
        use_catalog = any(
            v is not None
            for v in (
                query.category, query.language, query.country,
                query.min_participants, query.max_participants, query.sort,
            )
        )
        if use_catalog:
            params = {"limit": query.limit}
            for field_name, api_name in _CATALOG_PARAMS.items():
                val = getattr(query, field_name, None)
                if val is not None:
                    params[api_name] = val
            data = await self._get("/v1/catalog/search", params)
        else:
            if not query.term:
                raise CatalogProviderError("нужен term или хотя бы один фильтр каталога")
            data = await self._get(
                "/v1/channels/search", {"term": query.term, "limit": query.limit}
            )
        return [self._to_candidate(obj) for obj in _as_list(data)]

    def _to_candidate(self, obj: Any) -> CommunityCandidate:
        """Защитный парсинг: пробуем несколько возможных имён полей."""
        g = _getter(obj)
        username = g("username", "user_name", "link")
        if isinstance(username, str):
            username = username.rsplit("/", 1)[-1].lstrip("@") or None
        tg_id = _as_int(g("tg_id", "telegram_id", "channel_id"))
        kind = g("type", "kind") or ("chat" if g("is_group", "is_chat") else "channel")
        return CommunityCandidate(
            ref=f"@{username}" if username else str(g("internal_id", "id") or ""),
            channel_tg_id=tg_id,
            title=g("title", "name"),
            username=username,
            kind="chat" if str(kind).lower() in {"chat", "group", "supergroup"} else "channel",
            participants_count=_as_int(g("participants_count", "subscribers", "members", "subscribers_count")),
            language=g("language", "lang"),
            country=g("country", "geo"),
            category=g("category", "category_name"),
            er=_as_float(g("er", "engagement_rate")),
            verified=bool(g("verified", "is_verified")),
            provider=self.name,
            extra={"internal_id": g("internal_id", "id")},
        )


def _as_list(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "results", "channels", "list"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _getter(obj: Any):
    d = obj if isinstance(obj, dict) else {}

    def get(*keys: str) -> Any:
        for k in keys:
            if k in d and d[k] not in (None, ""):
                return d[k]
        return None

    return get


def _as_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# Статическая проверка соответствия протоколу.
_: CatalogProvider = TelemetrioProvider  # type: ignore[assignment]
