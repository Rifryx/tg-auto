"""Универсальный OpenAI-совместимый LLM-провайдер.

Используется для AnyModel (единый ключ + базовый URL, модель выбирается по
``model id``, напр. ``ag/gemini-3.1-flash-lite-preview`` / ``ds/deepseek-v4-flash``)
и для любого другого OpenAI-совместимого шлюза. Формат запроса — как у OpenAI
``/chat/completions``.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from worker.llm.base import LLMProvider, Message

# Явный потолок на запрос — иначе зависший шлюз держал бы генерацию бесконечно.
_REQUEST_TIMEOUT_SEC = 30.0


class OpenAICompatProvider(LLMProvider):
    def __init__(
        self,
        api_key: Optional[str],
        *,
        base_url: str,
        model: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = client  # инъекция для тестов

    async def generate(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 200,
        temperature: float = 0.8,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        url = f"{self._base_url}/chat/completions"

        client = self._client or httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SEC)
        try:
            response = await client.post(
                url, json=payload, headers=headers, timeout=_REQUEST_TIMEOUT_SEC
            )
            response.raise_for_status()
            data = response.json()
        finally:
            if self._client is None:
                await client.aclose()
        return data["choices"][0]["message"]["content"]
