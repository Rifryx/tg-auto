"""Тест ротации ключа шифрования через MultiFernet (этап 7, backlog #2)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from core.config import get_settings
from core.crypto import (
    CryptoError,
    decrypt_password,
    encrypt_password,
    reset_cache,
    rotate,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    """Каждый тест начинает с чистым кэшем Fernet и своим набором ключей."""
    reset_cache()
    get_settings.cache_clear()
    monkeypatch.setenv("DEV_MODE", "true")
    yield
    reset_cache()
    get_settings.cache_clear()


def _key() -> str:
    return Fernet.generate_key().decode()


def test_single_key_still_works(monkeypatch):
    """Обратная совместимость: один ключ без запятых — как раньше."""
    monkeypatch.setenv("ENCRYPTION_KEY", _key())
    enc = encrypt_password(b"secret")
    assert decrypt_password(enc) == b"secret"


def test_new_key_reads_old_blob(monkeypatch):
    """Пишем под ключом K1, потом ротируем ENV на K2,K1 — старый blob читается."""
    k1 = _key()
    monkeypatch.setenv("ENCRYPTION_KEY", k1)
    old_blob = encrypt_password(b"legacy")

    # Ротация: добавляем новый ключ первым (write), старый оставляем для read.
    reset_cache()
    get_settings.cache_clear()
    k2 = _key()
    monkeypatch.setenv("ENCRYPTION_KEY", f"{k2},{k1}")

    assert decrypt_password(old_blob) == b"legacy"

    new_blob = encrypt_password(b"fresh")
    assert decrypt_password(new_blob) == b"fresh"
    # Новый blob не тот же, что старый (разные keys):
    assert new_blob != old_blob


def test_rotate_transcodes_blob(monkeypatch):
    """rotate() переписывает старый blob под текущий write-ключ."""
    k1 = _key()
    monkeypatch.setenv("ENCRYPTION_KEY", k1)
    old_blob = encrypt_password(b"data")

    reset_cache()
    get_settings.cache_clear()
    k2 = _key()
    monkeypatch.setenv("ENCRYPTION_KEY", f"{k2},{k1}")

    rotated = rotate(old_blob)
    assert rotated != old_blob
    # После rotate он расшифровывается тем же MultiFernet:
    assert decrypt_password(rotated) == b"data"

    # После выпиливания старого ключа — старый blob уже не расшифруется,
    # а rotated — работает.
    reset_cache()
    get_settings.cache_clear()
    monkeypatch.setenv("ENCRYPTION_KEY", k2)

    assert decrypt_password(rotated) == b"data"
    with pytest.raises(CryptoError):
        decrypt_password(old_blob)


def test_invalid_key_raises_crypto_error(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "not-a-valid-fernet-key")
    with pytest.raises(CryptoError):
        encrypt_password(b"x")


def test_empty_key_raises_crypto_error(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", ",,,")
    with pytest.raises(CryptoError):
        encrypt_password(b"x")
