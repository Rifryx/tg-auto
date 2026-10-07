"""Сверка крипто-платежей: cron-страховка на случай, если on-demand-проверка
не случилась (пользователь закрыл Mini App, не вернувшись на экран оплаты).

Логика идемпотентного применения — общая (``core.billing.payments.confirm_payment``),
поэтому дублирование с on-demand-проверкой безопасно: второй проход увидит
``paid`` и ничего не сделает.

Crypto Pay API — синхронный httpx-клиент, поэтому зовём его в пуле потоков,
не блокируя событийный цикл воркера.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from core.billing import payments as payments_service
from core.billing.providers import cryptobot
from core.models.payment import Payment
from worker.tasks.logging import get_logger


async def reconcile_payments_impl(ctx: dict) -> dict[str, int]:
    session_factory = ctx["session_factory"]
    applied = 0
    checked = 0
    with session_factory() as session:
        # Сначала просрочим «мёртвые» pending, чтобы не опрашивать их вечно.
        payments_service.expire_stale_pending(session)

        pending = list(
            session.execute(
                select(Payment).where(
                    Payment.provider == "crypto",
                    Payment.status == "pending",
                    Payment.provider_invoice_id.is_not(None),
                )
            ).scalars()
        )
        if not pending:
            return {"checked": 0, "applied": 0}

        invoice_ids = [p.provider_invoice_id for p in pending if p.provider_invoice_id]
        checked = len(invoice_ids)
        try:
            paid_ids = await asyncio.to_thread(
                cryptobot.get_paid_invoice_ids, invoice_ids
            )
        except cryptobot.CryptoBotError as exc:
            get_logger().warning("billing.reconcile.provider_error", error=repr(exc))
            return {"checked": checked, "applied": 0}

        for payment in pending:
            if payment.provider_invoice_id in paid_ids:
                result = payments_service.confirm_payment(
                    session, payload=payment.payload
                )
                if result.outcome == "applied":
                    applied += 1

    get_logger().info("billing.reconcile.done", checked=checked, applied=applied)
    return {"checked": checked, "applied": applied}
