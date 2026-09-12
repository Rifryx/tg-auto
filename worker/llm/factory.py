"""Фабрика LLM-провайдеров с кэшем по имени (PROJECT-STAGES §7)."""

from __future__ import annotations

from worker.llm.base import LLMProvider
from worker.llm.deepseek import DeepSeekProvider
from worker.llm.gemini import GeminiProvider

_PROVIDERS = {
    "deepseek": DeepSeekProvider,
    "gemini": GeminiProvider,
}

_cache: dict[str, LLMProvider] = {}


def get_provider(name: str) -> LLMProvider:
    """Возвращает (кэшированный) провайдер по имени: 'deepseek' | 'gemini'."""
    if name in _cache:
        return _cache[name]
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
