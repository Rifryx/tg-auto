"""Фабрика LLM-провайдеров с кэшем по имени (PROJECT-STAGES §7)."""

from __future__ import annotations

from core.config import get_settings
from worker.llm.base import LLMProvider
from worker.llm.deepseek import DeepSeekProvider
from worker.llm.gemini import GeminiProvider
from worker.llm.openai_compat import OpenAICompatProvider

_PROVIDERS = {
    "deepseek": DeepSeekProvider,
    "gemini": GeminiProvider,
}

_cache: dict[str, LLMProvider] = {}


def _anymodel_provider(name: str, settings) -> LLMProvider:
    """OpenAI-совместимый провайдер поверх AnyModel для выбранного имени.

    Имя из кампании (deepseek/gemini) определяет только model id — ключ и
    базовый URL общие. Так один ключ AnyModel закрывает обе модели."""
    model = (
        settings.anymodel_model_gemini
        if name == "gemini"
        else settings.anymodel_model_deepseek
    )
    return OpenAICompatProvider(
        settings.anymodel_api_key,
        base_url=settings.anymodel_base_url,
        model=model,
    )


def get_provider(name: str) -> LLMProvider:
    """Возвращает (кэшированный) провайдер по имени: 'deepseek' | 'gemini'.

    Если задан AnyModel-ключ — оба имени идут через AnyModel (единый ключ,
    OpenAI-совместимый шлюз); иначе — прямые провайдеры DeepSeek/Gemini."""
    if name in _cache:
        return _cache[name]
    settings = get_settings()
    if settings.anymodel_api_key:
        provider: LLMProvider = _anymodel_provider(name, settings)
        _cache[name] = provider
        return provider
    provider_cls = _PROVIDERS.get(name)
    if provider_cls is None:
        allowed = ", ".join(sorted(_PROVIDERS))
        raise ValueError(f"Unknown LLM provider {name!r}. Allowed: {allowed}")
    provider = provider_cls()
    _cache[name] = provider
    return provider


def reset_cache() -> None:
    """Сбрасывает кэш провайдеров (тесты)."""
    _cache.clear()
