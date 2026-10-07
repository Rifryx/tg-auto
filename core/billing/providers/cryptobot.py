"""Клиент Crypto Pay API (@CryptoBot) — создание и сверка инвойсов.

Синхронный (httpx.Client): вызывается из sync-роутов API и из async cron'а
воркера через ``asyncio.to_thread``. Бизнес-логику применения платежа НЕ знает —
только общается с провайдером.

DEV-режим без токена: ``is_stub()`` == True. Тогда реальные вызовы не делаются;
создание инвойса возвращает фиктивный id/URL, а сверка считает инвойс
оплаченным — чтобы локальный поток оплаты проверялся без ключей и денег.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import httpx

from core.config import get_settings


@dataclass(frozen=True)
class CreatedInvoice:
    invoice_id: str
    pay_url: str


class CryptoBotError(RuntimeError):
    """Провайдер вернул ok=false или недоступен."""


def is_stub() -> bool:
    """Нет реального токена ⇒ работаем в stub-режиме (только DEV_MODE)."""
    settings = get_settings()
    return settings.dev_mode and not settings.cryptobot_api_token


def _headers() -> dict[str, str]:
    return {"Crypto-Pay-API-Token": get_settings().cryptobot_api_token or ""}


def create_invoice(
    *, amount: str, payload: str, description: str, expires_in: int = 900
) -> CreatedInvoice:
    """Создать инвойс. amount — строка (Crypto Pay требует строковую сумму)."""
    settings = get_settings()
    if is_stub():
        return CreatedInvoice(
            invoice_id=f"stub-{payload[:12]}",
            pay_url="https://t.me/CryptoTestnetBot",
        )
    body = {
        "asset": settings.cryptobot_asset,
        "amount": amount,
        "description": description,
        "payload": payload,
        "expires_in": expires_in,
    }
    try:
        resp = httpx.post(
            f"{settings.cryptobot_base_url}/createInvoice",
            json=body,
            headers=_headers(),
            timeout=15.0,
        )
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:  # сеть / не-JSON
        raise CryptoBotError(f"createInvoice failed: {exc!r}") from exc
    if not data.get("ok"):
        raise CryptoBotError(f"createInvoice error: {data.get('error')}")
    result = data["result"]
    return CreatedInvoice(
        invoice_id=str(result["invoice_id"]),
        pay_url=result.get("pay_url") or result.get("bot_invoice_url") or "",
    )


def get_paid_invoice_ids(invoice_ids: Iterable[str]) -> set[str]:
    """Из переданных id вернуть подмножество со статусом ``paid``.

    В stub-режиме считаем все переданные id оплаченными.
    """
    ids = [str(i) for i in invoice_ids if i]
    if not ids:
        return set()
    if is_stub():
        return set(ids)
    settings = get_settings()
    try:
        resp = httpx.get(
            f"{settings.cryptobot_base_url}/getInvoices",
            params={"invoice_ids": ",".join(ids)},
            headers=_headers(),
            timeout=15.0,
        )
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CryptoBotError(f"getInvoices failed: {exc!r}") from exc
    if not data.get("ok"):
        raise CryptoBotError(f"getInvoices error: {data.get('error')}")
    items = (data.get("result") or {}).get("items") or []
    return {
        str(it["invoice_id"]) for it in items if it.get("status") == "paid"
    }


def invoice_status(invoice_id: Optional[str]) -> Optional[str]:
    """Статус одного инвойса (``paid`` / иной / None)."""
    if not invoice_id:
        return None
    return "paid" if invoice_id in get_paid_invoice_ids([invoice_id]) else "pending"
