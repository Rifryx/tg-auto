"""Симметричное шифрование секретов (Fernet).

Ключ берётся из ``core.config`` (ENV ``ENCRYPTION_KEY``). Инстанс Fernet
кэшируется и пересоздаётся только при смене ключа. Любая ошибка ключа или
битых данных оборачивается в :class:`CryptoError` — наружу не летит сырое
исключение cryptography.
"""

from __future__ import annotations

from typing import Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

from core.config import get_settings


class CryptoError(Exception):
    """Ошибка шифрования/дешифрования (неверный ключ или битые данные)."""


_cache: Optional[Tuple[str, Fernet]] = None


def _get_fernet() -> Fernet:
    global _cache
    key = get_settings().encryption_key
    if _cache is None or _cache[0] != key:
        try:
            fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError) as exc:
            raise CryptoError(
                "Invalid ENCRYPTION_KEY: expected a 32-byte urlsafe base64 Fernet key"
            ) from exc
        _cache = (key, fernet)
    return _cache[1]


def _encrypt(plain: bytes) -> bytes:
    try:
        return _get_fernet().encrypt(plain)
    except CryptoError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise CryptoError("Encryption failed") from exc


def _decrypt(enc: bytes) -> bytes:
    try:
        return _get_fernet().decrypt(enc)
    except InvalidToken as exc:
        raise CryptoError("Decryption failed: invalid token or wrong key") from exc
    except CryptoError:
        raise
    except (TypeError, ValueError) as exc:
        raise CryptoError("Decryption failed: malformed ciphertext") from exc


def encrypt_session(plain: bytes) -> bytes:
    return _encrypt(plain)


def decrypt_session(enc: bytes) -> bytes:
    return _decrypt(enc)


def encrypt_password(plain: bytes) -> bytes:
    return _encrypt(plain)


def decrypt_password(enc: bytes) -> bytes:
    return _decrypt(enc)


def reset_cache() -> None:
    """Сбрасывает закэшированный инстанс Fernet (используется в тестах)."""

    global _cache
    _cache = None
