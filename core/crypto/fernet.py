"""Симметричное шифрование секретов (Fernet).

Ключ берётся из ``core.config`` (ENV ``ENCRYPTION_KEY``). Инстанс кэшируется
и пересоздаётся только при смене ключа. Любая ошибка ключа или битых данных
оборачивается в :class:`CryptoError` — наружу не летит сырое исключение
cryptography.

Ротация ключей (этап 7, backlog #2). ``ENCRYPTION_KEY`` может содержать
несколько ключей через запятую: первый используется для write, все — для
read (:class:`MultiFernet`). Так можно бесшовно ввести новый ключ, потом
дозакрыть перекодированием старых blob'ов и вычистить старый ключ из ENV.

Пример:

    ENCRYPTION_KEY=<new_key>,<old_key_1>,<old_key_2>

Новые записи пишутся ``new_key``; старые blob'ы, зашифрованные любым из
``old_key_*``, всё ещё расшифровываются. Один ключ — старое поведение.
"""

from __future__ import annotations

from typing import Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from core.config import get_settings


class CryptoError(Exception):
    """Ошибка шифрования/дешифрования (неверный ключ или битые данные)."""


_cache: Optional[Tuple[str, MultiFernet]] = None


def _parse_keys(raw: str) -> list[str]:
    """Разбирает ``ENCRYPTION_KEY`` (может быть одним ключом или списком через запятую)."""
    return [k.strip() for k in raw.split(",") if k.strip()]


def _get_fernet() -> MultiFernet:
    global _cache
    key = get_settings().encryption_key
    if _cache is None or _cache[0] != key:
        parts = _parse_keys(key if isinstance(key, str) else key.decode())
        if not parts:
            raise CryptoError("ENCRYPTION_KEY is empty")
        try:
            fernets = [Fernet(p.encode()) for p in parts]
        except (ValueError, TypeError) as exc:
            raise CryptoError(
                "Invalid ENCRYPTION_KEY: expected a 32-byte urlsafe base64 Fernet key "
                "(or a comma-separated list of such keys for rotation)"
            ) from exc
        _cache = (key, MultiFernet(fernets))
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


def rotate(enc: bytes) -> bytes:
    """Перекодировать blob под самый первый (write) ключ.

    Используется утилитой ротации: после ввода нового ключа читаем все
    blob'ы, вызываем rotate() и перезаписываем — потом старый ключ можно
    выкидывать. Возвращает новый шифротекст под текущим write-ключом.
    """
    try:
        return _get_fernet().rotate(enc)
    except InvalidToken as exc:
        raise CryptoError("Rotate failed: invalid token or unknown key") from exc
    except (TypeError, ValueError) as exc:
        raise CryptoError("Rotate failed: malformed ciphertext") from exc


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
