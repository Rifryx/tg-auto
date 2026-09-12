"""Абстракция LLM-провайдера (PROJECT-STAGES §7).

SHARED-код: используется постингом коммента и будущим парсером. Провайдеры не
пишут в БД и ничего не постят — только генерация текста.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Message:
    """Одно сообщение диалога для LLM."""

    role: str  # "user" | "assistant"
    content: str


class LLMProvider(ABC):
    """Единый интерфейс генерации текста поверх конкретного LLM."""

    @abstractmethod
    async def generate(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 200,
        temperature: float = 0.8,
    ) -> str:
        """Возвращает сгенерированный текст по system-промпту и истории."""
        raise NotImplementedError
