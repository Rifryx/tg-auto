"""Gemini через google-generativeai (free tier) (PROJECT-STAGES §7).

``google-generativeai`` импортируется лениво — модуль грузится и тестируется
(с инъекцией ``model``) без установленного пакета.
"""

from __future__ import annotations

from typing import Any, Optional

from core.config import get_settings
from worker.llm.base import LLMProvider, Message

DEFAULT_MODEL = "gemini-1.5-flash"


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        model_name: str = DEFAULT_MODEL,
        model: Any = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else get_settings().gemini_api_key
        self._model_name = model_name
        self._model = model  # инъекция для тестов

    def _get_model(self) -> Any:
        if self._model is None:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)
            self._model = genai.GenerativeModel(self._model_name)
        return self._model

    async def generate(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 200,
        temperature: float = 0.8,
    ) -> str:
        model = self._get_model()
        # Gemini не различает system-роль: кладём system-инструкцию в начало.
        parts = [system] + [f"{m.role}: {m.content}" for m in messages]
        prompt = "\n".join(parts)
        response = await model.generate_content_async(
            prompt,
            generation_config={
                "max_output_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        return response.text
