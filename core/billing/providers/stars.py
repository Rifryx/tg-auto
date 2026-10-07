"""Создание инвойса Telegram Stars через Bot API ``createInvoiceLink``.

Оплата Stars подтверждается ботом (``pre_checkout_query`` + ``successful_payment``
в :mod:`bot.payments`), а не здесь. Этот модуль лишь выдаёт ссылку на инвойс,
которую фронт открывает через ``WebApp.openInvoice``.

Валюта Stars — ``XTR``; ``provider_token`` для Stars ПУСТОЙ (это обязательное
условие Bot API для цифровых товаров за звёзды).

DEV-режим без токена бота: ``is_stub()`` == True — возвращаем deep-link-заглушку,
а подтверждение в stub-потоке делает check-эндпоинт.
"""
from __future__ import annotations

import httpx

from core.config import get_settings


def is_stub() -> bool:
    settings = get_settings()
    return settings.dev_mode and not settings.telegram_bot_token


class StarsError(RuntimeError):
    pass


def create_invoice_link(*, title: str, description: str, payload: str, stars: int) -> str:
    """Вернуть ссылку на инвойс Stars (``t.me/$...`` / ``tg://``)."""
    settings = get_settings()
    if is_stub():
        return f"https://t.me/invoice/stub-{payload[:12]}"
    token = settings.telegram_bot_token
    if not token:
        raise StarsError("TELEGRAM_BOT_TOKEN is not set")
    body = {
        "title": title,
        "description": description,
        "payload": payload,
        "provider_token": "",  # Stars: обязательно пустой
        "currency": "XTR",
        "prices": [{"label": title, "amount": int(stars)}],
    }
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/createInvoiceLink",
            json=body,
            timeout=15.0,
        )
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise StarsError(f"createInvoiceLink failed: {exc!r}") from exc
    if not data.get("ok"):
        raise StarsError(f"createInvoiceLink error: {data.get('description')}")
    return str(data["result"])
