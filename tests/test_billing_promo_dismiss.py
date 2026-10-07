"""Шторка акции показывается один раз: после dismiss пользователь её не видит."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps.auth import require_user
from api.deps.db import get_session
from api.routers import billing as billing_router
from core.models.promotion import Promotion


def _app(session, user_id="user-1") -> FastAPI:
    app = FastAPI()
    app.include_router(billing_router.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: user_id
    return app


def _seed_active_promo(session) -> Promotion:
    now = datetime.now(timezone.utc)
    promo = Promotion(
        title="Чёрная пятница",
        description="−50% на Pro",
        kind="percent",
        percent_off=50,
        badge_variant="fire",
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=1),
        enabled=True,
    )
    session.add(promo)
    session.flush()
    return promo


def test_promo_visible_then_hidden_after_dismiss(session):
    promo = _seed_active_promo(session)
    client = TestClient(_app(session))

    r1 = client.get("/billing/promo")
    assert r1.status_code == 200
    assert r1.json()["promo"]["id"] == promo.id

    r2 = client.post(f"/billing/promo/{promo.id}/dismiss")
    assert r2.status_code == 200

    r3 = client.get("/billing/promo")
    assert r3.json()["promo"] is None


def test_dismiss_is_per_user(session):
    promo = _seed_active_promo(session)
    # user-1 скрыл.
    TestClient(_app(session, "user-1")).post(f"/billing/promo/{promo.id}/dismiss")
    # user-2 всё ещё видит.
    r = TestClient(_app(session, "user-2")).get("/billing/promo")
    assert r.json()["promo"]["id"] == promo.id
