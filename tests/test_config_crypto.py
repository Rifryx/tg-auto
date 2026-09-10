from __future__ import annotations

from datetime import time

import pytest
from cryptography.fernet import Fernet

import core.crypto as crypto
from core.config import Settings, get_settings
from core.crypto import (
    CryptoError,
    decrypt_password,
    decrypt_session,
    encrypt_password,
    encrypt_session,
)

_CONFIG_ENV_VARS = [
    "ENCRYPTION_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "DEV_MODE",
    "DEFAULT_ACTIVE_HOURS_START",
    "DEFAULT_ACTIVE_HOURS_END",
    "DEFAULT_ACTIVE_HOURS_TZ",
]


@pytest.fixture
def env(monkeypatch):
    """Чистое окружение + сброшенные кэши конфига и crypto."""
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    crypto.reset_cache()
    yield monkeypatch
    get_settings.cache_clear()
    crypto.reset_cache()


def _valid_key() -> str:
    return Fernet.generate_key().decode()


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def test_dev_mode_valid_without_llm_keys(env):
    env.setenv("ENCRYPTION_KEY", _valid_key())
    env.setenv("DEV_MODE", "true")

    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.dev_mode is True
    # dev подставляет заглушки — конфиг валиден без реальных секретов
    assert settings.telegram_api_id is not None
    assert settings.has_llm is True
    # кэширование
    assert get_settings() is settings
    # окна активности по умолчанию
    assert settings.default_active_hours_start == time(9, 0)
    assert settings.default_active_hours_tz == "Europe/Kiev"


def test_prod_invalid_without_llm_keys(env):
    env.setenv("ENCRYPTION_KEY", _valid_key())
    env.setenv("TELEGRAM_API_ID", "12345")
    env.setenv("TELEGRAM_API_HASH", "abcdef")
    # DEV_MODE не задан → боевой режим, LLM-ключей нет

    with pytest.raises(RuntimeError):
        get_settings()


def test_prod_valid_with_one_llm_key(env):
    env.setenv("ENCRYPTION_KEY", _valid_key())
    env.setenv("TELEGRAM_API_ID", "12345")
    env.setenv("TELEGRAM_API_HASH", "abcdef")
    env.setenv("DEEPSEEK_API_KEY", "sk-real")

    settings = get_settings()
    assert settings.dev_mode is False
    assert settings.has_llm is True


def test_missing_encryption_key_names_the_variable(env):
    # DEV_MODE снимает требования Telegram/LLM, но ENCRYPTION_KEY обязателен всегда
    env.setenv("DEV_MODE", "true")

    with pytest.raises(RuntimeError) as excinfo:
        get_settings()
    assert "ENCRYPTION_KEY" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# crypto
# --------------------------------------------------------------------------- #
def test_session_roundtrip(env):
    env.setenv("ENCRYPTION_KEY", _valid_key())
    env.setenv("DEV_MODE", "true")

    plain = b"telethon .session raw bytes \x00\x01\x02"
    enc = encrypt_session(plain)
    assert enc != plain
    assert decrypt_session(enc) == plain


def test_password_roundtrip(env):
    env.setenv("ENCRYPTION_KEY", _valid_key())
    env.setenv("DEV_MODE", "true")

    plain = b"proxy-secret-password"
    enc = encrypt_password(plain)
    assert enc != plain
    assert decrypt_password(enc) == plain


def test_decrypt_garbage_raises_cryptoerror(env):
    env.setenv("ENCRYPTION_KEY", _valid_key())
    env.setenv("DEV_MODE", "true")

    with pytest.raises(CryptoError):
        decrypt_session(b"this-is-not-a-valid-fernet-token")
    with pytest.raises(CryptoError):
        decrypt_password(b"\x00\x01\x02\x03garbage")


def test_decrypt_with_wrong_key_raises_cryptoerror(env):
    env.setenv("ENCRYPTION_KEY", _valid_key())
    env.setenv("DEV_MODE", "true")
    token = encrypt_session(b"secret")

    # меняем ключ — старый токен больше не расшифровывается
    env.setenv("ENCRYPTION_KEY", _valid_key())
    get_settings.cache_clear()
    crypto.reset_cache()

    with pytest.raises(CryptoError):
        decrypt_session(token)


def test_invalid_encryption_key_raises_cryptoerror(env):
    # конфиг принимает любую строку, но Fernet отвергнет неверный ключ
    env.setenv("ENCRYPTION_KEY", "not-a-valid-base64-fernet-key")
    env.setenv("DEV_MODE", "true")

    with pytest.raises(CryptoError):
        encrypt_session(b"data")
