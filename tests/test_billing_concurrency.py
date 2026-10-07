"""Гонка подтверждений одного платежа → подписка продлевается РОВНО один раз.

В отличие от остальных биллинг-тестов здесь нужны настоящие параллельные
соединения (а не savepoint-изоляция фикстуры ``session``), чтобы проверить
сериализацию через ``SELECT … FOR UPDATE``. Поэтому тест работает напрямую с
``engine`` и за собой прибирает (реальные commit'ы).
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from core.billing import payments as payments_service
from core.models.pricing import PricingConfig
from core.repositories.subscription import SubscriptionRepository

_USER = "u-concurrency"


def _cleanup(Session_) -> None:
    with Session_() as s:
        s.execute(text("DELETE FROM payments WHERE user_id = :u"), {"u": _USER})
        s.execute(text("DELETE FROM subscriptions WHERE user_id = :u"), {"u": _USER})
        s.commit()


def test_parallel_confirm_applies_once(engine):
    Session_ = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    _cleanup(Session_)
    try:
        with Session_() as s:
            cfg = s.get(PricingConfig, 1)
            cfg.period_days = 30
            cfg.price_usdt = Decimal("20.00")
            cfg.price_stars = 1000
            s.commit()
            payment = payments_service.create_payment(s, _USER, "crypto")
            payload = payment.payload

        start = threading.Barrier(2)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            with Session_() as s:
                start.wait(timeout=10)
                res = payments_service.confirm_payment(s, payload=payload)
                with lock:
                    outcomes.append(res.outcome)

        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = [ex.submit(worker), ex.submit(worker)]
            for f in futures:
                f.result(timeout=30)

        # Ровно одно применение; второй проход — идемпотентный no-op.
        assert sorted(outcomes) == ["already_applied", "applied"]

        with Session_() as s:
            exp = SubscriptionRepository(s).get(_USER).expires_at
        now = datetime.now(timezone.utc)
        # Период добавился один раз (~30 дней), а не два (~60).
        assert timedelta(days=29) < (exp - now) < timedelta(days=31)
    finally:
        _cleanup(Session_)
