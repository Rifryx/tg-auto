"""Чистые парсеры ссылок Telegram (worker-scope).

Используются :mod:`modules.commenting.worker.channels`, bulk-actions канала/
чата и любым другим воркер-кодом, которому нужно преобразовать «сырой» ввод
пользователя (``@username`` / ``t.me/foo`` / ``t.me/+hash`` / ``t.me/addlist/slug``)
в форму, пригодную для Telethon.

Без БД, без сети — только regex/строки.
"""

from __future__ import annotations

from typing import Optional


def strip_url(ref: str) -> str:
    """Убирает scheme и хост, оставляя «путь» ссылки."""
    ref = ref.strip()
    for prefix in ("https://", "http://"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
    if ref.startswith("t.me/"):
        ref = ref[len("t.me/"):]
    elif ref.startswith("telegram.me/"):
        ref = ref[len("telegram.me/"):]
    return ref.strip("/")


def folder_slug(ref: str) -> Optional[str]:
    """Слаг папки-addlist (``t.me/addlist/<slug>``) или ``None``."""
    body = strip_url(ref)
    if body.startswith("addlist/"):
        return body[len("addlist/"):] or None
    return None


def invite_hash(ref: str) -> Optional[str]:
    """Хэш приватного инвайта (``t.me/+xxxx`` / ``t.me/joinchat/xxxx``) или ``None``."""
    body = strip_url(ref)
    if body.startswith("+"):
        return body[1:] or None
    if body.startswith("joinchat/"):
        return body[len("joinchat/"):] or None
    return None


def public_ref(ref: str) -> str:
    """Публичный ``@username`` / имя канала без префиксов."""
    return strip_url(ref).lstrip("@")


def classify_ref(ref: str) -> str:
    """Тип ссылки: ``folder`` / ``invite`` / ``public``."""
    if folder_slug(ref) is not None:
        return "folder"
    if invite_hash(ref) is not None:
        return "invite"
    return "public"
