"""Конфигурация приложения (pydantic-settings).

Все секреты читаются из ENV. Критичный секрет ``ENCRYPTION_KEY`` обязателен
всегда; при его отсутствии ``get_settings()`` бросает понятный ``RuntimeError``
с именем переменной. В боевом режиме дополнительно обязательны Telegram-креды и
хотя бы один LLM-ключ. ``DEV_MODE=true`` ослабляет эти требования: разрешает
фиктивный initData и подставляет dummy-ключи LLM/Telegram.
"""

from __future__ import annotations

from datetime import time
from functools import lru_cache
from typing import Optional

from pydantic import ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Заглушки для DEV_MODE — реальные вызовы Telegram/LLM в dev не выполняются.
_DEV_TELEGRAM_API_ID = 0
_DEV_TELEGRAM_API_HASH = "dev-telegram-api-hash"
_DEV_LLM_KEY = "dev-dummy-llm-key"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Инфраструктура (имеют dev-дефолты из docker-compose) ---
    database_url: str = "postgresql+psycopg://neuro:neuro@localhost:5432/neuro"
    redis_url: str = "redis://localhost:6379/0"

    # --- Telegram (обязательны вне DEV_MODE) ---
    telegram_api_id: Optional[int] = None
    telegram_api_hash: Optional[str] = None

    # --- Критичный секрет: обязателен всегда ---
    encryption_key: str

    # --- LLM (optional; вне DEV_MODE нужен хотя бы один) ---
    deepseek_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None

    # --- Режим ---
    dev_mode: bool = False

    # --- Окна активности по умолчанию ---
    default_active_hours_start: time = time(9, 0)
    default_active_hours_end: time = time(23, 0)
    default_active_hours_tz: str = "Europe/Kiev"

    @property
    def has_llm(self) -> bool:
        return bool(self.deepseek_api_key or self.gemini_api_key)

    @model_validator(mode="after")
    def _validate_mode(self) -> "Settings":
        if self.dev_mode:
            # Подставляем безопасные заглушки, чтобы конфиг был валиден без секретов.
            if self.telegram_api_id is None:
                self.telegram_api_id = _DEV_TELEGRAM_API_ID
            if not self.telegram_api_hash:
                self.telegram_api_hash = _DEV_TELEGRAM_API_HASH
            if not self.has_llm:
                self.deepseek_api_key = self.deepseek_api_key or _DEV_LLM_KEY
            return self

        missing: list[str] = []
        if self.telegram_api_id is None:
            missing.append("TELEGRAM_API_ID")
        if not self.telegram_api_hash:
            missing.append("TELEGRAM_API_HASH")
        if missing:
            raise ValueError(
                "Missing required environment variables (or set DEV_MODE=true): "
                + ", ".join(missing)
            )
        if not self.has_llm:
            raise ValueError(
                "At least one LLM API key is required (DEEPSEEK_API_KEY or "
                "GEMINI_API_KEY), or set DEV_MODE=true"
            )
        return self


# Соответствие имён полей → ENV-переменных для понятных сообщений об ошибках.
_ENV_NAME = {
    "encryption_key": "ENCRYPTION_KEY",
    "database_url": "DATABASE_URL",
    "redis_url": "REDIS_URL",
    "telegram_api_id": "TELEGRAM_API_ID",
    "telegram_api_hash": "TELEGRAM_API_HASH",
}


def _build_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        missing = [
            _ENV_NAME.get(str(err["loc"][0]), str(err["loc"][0]).upper())
            for err in exc.errors()
            if err["type"] == "missing"
        ]
        if missing:
            raise RuntimeError(
                "Missing required environment variable(s): " + ", ".join(sorted(set(missing)))
            ) from exc
        # Ошибки бизнес-правил (например, отсутствие LLM-ключа вне DEV_MODE).
        messages = "; ".join(err.get("msg", "") for err in exc.errors())
        raise RuntimeError(f"Invalid configuration: {messages}") from exc


@lru_cache
def get_settings() -> Settings:
    """Возвращает единый закэшированный экземпляр настроек.

    Кэш сбрасывается через ``get_settings.cache_clear()`` (используется в тестах).
    """

    return _build_settings()
