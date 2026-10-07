"""Обработка оплаты Telegram Stars в боте (aiogram v3).

Ссылку на инвойс создаёт API (``core.billing.providers.stars``); бот отвечает за
два апдейта Telegram:

* ``pre_checkout_query`` — последняя проверка перед списанием. Находим pending
  платёж по ``invoice_payload``, сверяем валюту (XTR) и сумму (звёзды). Ответить
  ОБЯЗАТЕЛЬНО (иначе Telegram отменит оплату через ~10 сек).
* ``successful_payment`` — деньги списаны. Идемпотентно применяем платёж
  (``confirm_payment``) и продлеваем подписку. ``telegram_payment_charge_id``
  сохраняем как ``provider_invoice_id`` — он же понадобится для возврата.

Доступ к БД — через уже настроенную фабрику сессий ``api.deps.db._session_factory``.
"""
from __future__ import annotations

import logging

from aiogram.types import Message, PreCheckoutQuery
from sqlalchemy import select

from api.deps.db import _session_factory
from core.billing import payments as payments_service
from core.models.payment import Payment

logger = logging.getLogger("bot.payments")


async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    payload = query.invoice_payload
    ok = False
    reason = "Платёж не найден или устарел. Начните оплату заново."
    with _session_factory()() as session:
        payment = session.execute(
            select(Payment).where(Payment.payload == payload)
        ).scalars().first()
        if payment is None:
            pass
        elif payment.status != "pending":
            reason = "Этот платёж уже обработан."
        elif query.currency != "XTR" or query.total_amount != payment.price_stars:
            reason = "Сумма платежа не совпадает. Обновите страницу оплаты."
        else:
            ok = True
    try:
        if ok:
            await query.answer(ok=True)
        else:
            await query.answer(ok=False, error_message=reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning("bot.payments.pre_checkout_answer_failed: %r", exc)


async def on_successful_payment(message: Message) -> None:
    sp = message.successful_payment
    if sp is None:
        return
    with _session_factory()() as session:
        result = payments_service.confirm_payment(
            session,
            payload=sp.invoice_payload,
            set_invoice_id=sp.telegram_payment_charge_id,
        )
    if result.outcome in ("applied", "already_applied"):
        await message.answer(
            "✅ Оплата получена. Подписка <b>Pro</b> активна.",
            parse_mode="HTML",
        )
    else:
        # Деньги списаны, но платёж не найден — это аномалия, логируем громко.
        logger.error(
            "bot.payments.successful_but_%s payload=%s charge=%s",
            result.outcome,
            sp.invoice_payload,
            sp.telegram_payment_charge_id,
        )
        await message.answer(
            "⚠️ Оплата получена, но возникла заминка с активацией. "
            "Мы уже разбираемся — подписка будет активирована."
        )
