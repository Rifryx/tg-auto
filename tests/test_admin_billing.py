"""Админка биллинга: цена, акции (с валидацией пересечения), аналитика, доступ."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps.admin import require_admin
from api.deps.auth import require_user
from api.deps.db import get_session
from api.routers import admin as admin_router


def _admin_app(session) -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_admin] = lambda: "admin-1"
    app.dependency_overrides[require_user] = lambda: "admin-1"
    return app


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_put_pricing_updates_base(session):
    client = TestClient(_admin_app(session))
    r = client.put(
        "/admin/pricing",
        json={"price_usdt": "29.50", "price_stars": 1500, "period_days": 31},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["price_usdt"] == 29.5
    assert body["price_stars"] == 1500
    assert body["period_days"] == 31


def test_analytics_shape(session):
    client = TestClient(_admin_app(session))
    r = client.get("/admin/analytics")
    assert r.status_code == 200
    body = r.json()
    for key in ("users", "revenue", "activity", "load"):
        assert key in body
    assert "pro_active" in body["users"]
    assert "accounts_by_status" in body["activity"]


def test_promotion_crud_and_overlap(session):
    client = TestClient(_admin_app(session))
    now = datetime.now(timezone.utc)

    # Создать активную percent-акцию.
    r1 = client.post(
        "/admin/promotions",
        json={
            "title": "Старт",
            "kind": "percent",
            "percent_off": 30,
            "badge_variant": "gold",
            "starts_at": _iso(now - timedelta(hours=1)),
            "ends_at": _iso(now + timedelta(hours=1)),
            "enabled": True,
        },
    )
    assert r1.status_code == 201, r1.text
    promo_id = r1.json()["id"]

    # Пересекающаяся включённая акция — запрещена (400).
    r2 = client.post(
        "/admin/promotions",
        json={
            "title": "Конфликт",
            "kind": "percent",
            "percent_off": 10,
            "starts_at": _iso(now),
            "ends_at": _iso(now + timedelta(hours=2)),
            "enabled": True,
        },
    )
    assert r2.status_code == 400

    # Невалидный percent_off.
    r3 = client.post(
        "/admin/promotions",
        json={
            "title": "Плохой",
            "kind": "percent",
            "percent_off": 0,
            "starts_at": _iso(now + timedelta(days=2)),
            "ends_at": _iso(now + timedelta(days=3)),
            "enabled": True,
        },
    )
    assert r3.status_code == 400

    # Список содержит созданную.
    r4 = client.get("/admin/promotions")
    assert any(p["id"] == promo_id for p in r4.json())

    # Удаление.
    r5 = client.delete(f"/admin/promotions/{promo_id}")
    assert r5.status_code == 200
    r6 = client.get("/admin/promotions")
    assert all(p["id"] != promo_id for p in r6.json())


def test_analytics_timeseries_shape(session):
    client = TestClient(_admin_app(session))
    r = client.get("/admin/analytics/timeseries?days=7")
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 7
    assert len(body["series"]) == 7
    for pt in body["series"]:
        assert {"date", "new_users", "payments", "comments"} <= set(pt)


def test_non_admin_gets_404(session):
    app = FastAPI()
    app.include_router(admin_router.router)
    app.dependency_overrides[get_session] = lambda: session
    # require_user есть, но user не в админах → require_admin вернёт 404.
    app.dependency_overrides[require_user] = lambda: "not-admin"
    r = TestClient(app).get("/admin/analytics")
    assert r.status_code == 404
