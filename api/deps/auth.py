"""Авторизация Telegram Mini App по ``initData`` (PROJECT-STAGES §6, §10).

Единственный доверенный источник ``user_id`` — поле ``user`` из initData,
подписанного секретом бота (``HMAC_SHA256("WebAppData", bot_token)``).
Клиент не может подменить user_id: любая правка ломает подпись.

Возвращаемое значение — строковое числовое ``id`` Telegram-пользователя
(например ``"12345678"``). Именно оно используется как PK подписок и для
проверки админ-прав. Никогда не принимаем user_id из заголовка/тела запроса.

В ``DEV_MODE`` (из ``core.config``) подпись не проверяется, id берётся из
``X-Dev-User`` — так удобно тестировать локально без Mini App. **DEV_MODE
запрещено включать в проде**: он превращает недоверенный заголовок в личность.
"""

from __future__ import annotations

import hashlib
import hmac
import json
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


def _extract_user_id(fields: dict[str, str]) -> Optional[str]:
    """Достаёт числовой id из JSON-поля ``user``. Возвращает str или None."""
    raw = fields.get("user")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    uid = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(uid, (int, str)):
        return None
    return str(uid)


async def require_user(
    x_telegram_init_data: Optional[str] = Header(default=None, alias=_INIT_DATA_HEADER),
    x_dev_user: Optional[str] = Header(default=None, alias=_DEV_USER_HEADER),
) -> str:
    """Возвращает Telegram user_id из подписанного initData или бросает 401."""
    settings = get_settings()

    if settings.dev_mode:
        # DEV_MODE=true в проде — критическая уязвимость. Никогда не включать.
        return x_dev_user or "dev-user"

    if not x_telegram_init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Telegram initData",
        )
    bot_token = settings.telegram_bot_token
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
    user_id = _extract_user_id(fields)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="initData missing user id",
        )
    return user_id
