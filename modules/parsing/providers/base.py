"""Абстракция провайдера каталога сообществ (Discovery, этап 3).

Нативный Telegram не ищет каналы/чаты по теме/подписчикам — это делают внешние
каталоги (Telemetr.io, TGStat). Провайдеры прячутся за единым интерфейсом, чтобы
их можно было менять/добавлять без переписывания discovery-флоу.

Провайдер отдаёт КАНДИДАТОВ; живую проверку (подписчики, linked-чат, свежесть)
делает нативный ``community_enrich`` — каталог бывает устаревшим.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


@dataclass
class CatalogQuery:
    term: Optional[str] = None          # ключевое слово (название/описание)
    category: Optional[str] = None      # id/слаг категории провайдера
    language: Optional[str] = None      # ISO-код языка
    country: Optional[str] = None       # ISO-код страны
    min_participants: Optional[int] = None
    max_participants: Optional[int] = None
    kind: Optional[str] = None          # "channel" | "chat" | None
    sort: Optional[str] = None          # members|growth|views|er|mentions
    limit: int = 50


@dataclass
class CommunityCandidate:
    """Найденное сообщество (до нативной верификации)."""

    ref: str                            # @username / t.me-ссылка для последующего enrich
    channel_tg_id: Optional[int] = None
    title: Optional[str] = None
    username: Optional[str] = None
    kind: str = "channel"
    participants_count: Optional[int] = None
    language: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None
    er: Optional[float] = None
    verified: bool = False
    provider: str = ""
    extra: dict = field(default_factory=dict)


class CatalogProviderError(RuntimeError):
    """Ошибка провайдера (нет ключа, сеть, квота, неверный ответ)."""


@runtime_checkable
class CatalogProvider(Protocol):
    name: str

    async def check(self) -> dict:
        """Проверка доступа/квоты (не тратит основную квоту, если возможно)."""
        ...

    async def search(self, query: CatalogQuery) -> list[CommunityCandidate]:
        """Поиск сообществ по критериям каталога."""
        ...
