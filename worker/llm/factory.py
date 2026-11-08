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


def other_provider_name(primary: str) -> str:
    """Имя второго провайдера (deepseek↔gemini) — для сообщений/логов."""
    return "gemini" if primary == "deepseek" else "deepseek"


def fallback_provider(primary_name: str) -> LLMProvider | None:
    """Второй провайдер, если для него есть рабочий путь — страховка на
    случай, когда у выбранного провайдера ключ пустой/битый/недоступен
    (401, таймаут, квота и т.п.). Модель больше НЕ выбирает пользователь
    (убрано из UI — ему это ничего не даёт решать), так что эта функция —
    единственный способ «переключиться», когда что-то пошло не так.

    AnyModel (единый ключ на оба имени) считается рабочим путём для
    фолбэка независимо от того, заданы ли отдельные DEEPSEEK_API_KEY/
    GEMINI_API_KEY — раньше фолбэк молчал в AnyModel-режиме именно из-за
    этого несовпадения (ключ есть, но не под тем именем настройки)."""
    # Локальный импорт (не модульный): тесты монкипатчат core.config.get_settings
    # по месту вызова — модульный `from ... import get_settings` зафиксировал
    # бы оригинал на момент импорта модуля и не увидел бы подмену.
    from core.config import get_settings

    settings = get_settings()
    other = other_provider_name(primary_name)
    has_path = bool(getattr(settings, "anymodel_api_key", None)) or bool(
        getattr(settings, f"{other}_api_key", None)
    )
    if not has_path:
        return None
    try:
        return get_provider(other)
    except Exception:  # noqa: BLE001
        return None
