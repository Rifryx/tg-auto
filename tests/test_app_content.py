"""Редактируемый контент приложения: «О приложении» и конфиг поддержки."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps.admin import require_admin
from api.deps.auth import require_user
from api.deps.db import get_session
from api.routers import admin as admin_router
from api.routers import app_content as content_router


def _app(session) -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router.router)
    app.include_router(content_router.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_admin] = lambda: "admin-1"
    app.dependency_overrides[require_user] = lambda: "user-1"
    return app


def test_activity_settings_default_then_edit(session):
    client = TestClient(_app(session))

    # Дефолт.
    r = client.get("/app/content")
    assert r.status_code == 200
    assert r.json()["activity"]["timezone"] == "UTC"

    # Сохраняем таймзону и окно.
    r2 = client.put(
        "/app/settings/activity",
        json={"timezone": "Asia/Almaty", "window_start": "08:00", "window_end": "22:00"},
    )
    assert r2.status_code == 200, r2.text

    got = client.get("/app/content").json()["activity"]
    assert got["timezone"] == "Asia/Almaty"
    assert got["window_start"] == "08:00"
    assert got["window_end"] == "22:00"


def test_plans_default_then_edit(session):
    client = TestClient(_app(session))

    # Дефолт присутствует.
    r = client.get("/app/content")
    assert r.status_code == 200
    assert r.json()["plans"]["pro"]["tagline"]

    # Админ правит витрину тарифов.
    r2 = client.put(
        "/admin/app-content/plans",
        json={
            "free": {"tagline": "Бесплатно", "bullets": ["1 аккаунт"]},
            "pro": {"tagline": "Всё включено", "bullets": ["Безлимит", "Поддержка 24/7"]},
        },
    )
    assert r2.status_code == 200, r2.text

    plans = client.get("/app/content").json()["plans"]
    assert plans["free"]["tagline"] == "Бесплатно"
    assert plans["pro"]["bullets"] == ["Безлимит", "Поддержка 24/7"]


def test_activity_rejects_bad_timezone(session):
    client = TestClient(_app(session))
    r = client.put(
        "/app/settings/activity",
        json={"timezone": "Mars/Phobos", "window_start": "09:00", "window_end": "23:00"},
    )
    assert r.status_code == 422


def test_about_defaults_then_edit(session):
    client = TestClient(_app(session))

    # До правок — дефолт.
    r = client.get("/app/content")
    assert r.status_code == 200
    assert r.json()["about"]["app_name"] == "CAT"

    # Админ меняет блок «О приложении».
    r2 = client.put(
        "/admin/app-content/about",
        json={"app_name": "MySoft", "version": "2.0", "body": "Новое описание"},
    )
    assert r2.status_code == 200, r2.text

    # Пользователь видит обновлённое.
    r3 = client.get("/app/content")
    about = r3.json()["about"]
    assert about["app_name"] == "MySoft"
    assert about["version"] == "2.0"
    assert about["body"] == "Новое описание"


def test_support_edit_and_public_fields(session):
    client = TestClient(_app(session))

    r = client.put(
        "/admin/app-content/support",
        json={
            "manager_username": "@Support_Man",
            "manager_url": "https://t.me/support",
            "in_app_enabled": False,
            "intro": "Напишите нам",
        },
    )
    assert r.status_code == 200, r.text
    # username нормализован (без @).
    assert r.json()["manager_username"] == "Support_Man"

    pub = client.get("/app/content").json()["support"]
    assert pub["manager_username"] == "Support_Man"
    assert pub["manager_url"] == "https://t.me/support"
    assert pub["in_app_enabled"] is False
    assert pub["intro"] == "Напишите нам"
