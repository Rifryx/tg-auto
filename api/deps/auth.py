"""Авторизация Telegram Mini App по ``initData`` (PROJECT-STAGES §6, §10).

Валидация подписи ``initData`` идёт по алгоритму Telegram WebApp: секрет —
``HMAC_SHA256("WebAppData", bot_token)``, затем сверяется ``HMAC_SHA256(secret,
data_check_string)`` с полем ``hash``. Bot-token берётся из окружения
(``TELEGRAM_BOT_TOKEN``) — это конфиг именно API-слоя, в core он не заводится.

В ``DEV_MODE`` (из ``core.config``) проверка отключается: пропускаем всё,
идентификатор пользователя берём из заголовка ``X-Dev-User`` (заглушка для
локальной разработки без реального Telegram).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, status

from core.config import get_settings

_INIT_DATA_HEADER = "X-Telegram-Init-Data"
_DEV_USER_HEADER = "X-Dev-User"


def _parse_and_verify(init_data: str, bot_token: str) -> Optional[dict[str, str]]:
    """Проверяет подпись initData; при успехе возвращает разобранные поля."""
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=False))
    except ValueError:
        return None
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        return None
    return pairs


async def require_user(
    x_telegram_init_data: Optional[str] = Header(default=None, alias=_INIT_DATA_HEADER),
    x_dev_user: Optional[str] = Header(default=None, alias=_DEV_USER_HEADER),
) -> str:
    """Возвращает идентификатор пользователя Mini App или бросает 401."""
    if get_settings().dev_mode:
        return x_dev_user or "dev-user"

    if not x_telegram_init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Telegram initData",
        )
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Auth is not configured (TELEGRAM_BOT_TOKEN unset)",
        )
    fields = _parse_and_verify(x_telegram_init_data, bot_token)
    if fields is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram initData",
        )
    return fields.get("user", "")
