"""DeepSeek через OpenAI-совместимый REST-эндпоинт (PROJECT-STAGES §7)."""

from __future__ import annotations

from typing import Any, Optional

import httpx

from core.config import get_settings
from worker.llm.base import LLMProvider, Message

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


class DeepSeekProvider(LLMProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else get_settings().deepseek_api_key
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

        client = self._client or httpx.AsyncClient()
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        finally:
            if self._client is None:
                await client.aclose()
        return data["choices"][0]["message"]["content"]
