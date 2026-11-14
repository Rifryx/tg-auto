"""Мульти-тенантность: изоляция корневых сущностей между пользователями.

Проверяем, что аккаунты / персоны / прокси одного Telegram-пользователя не
видны и не изменяемы другим (это была критичная дыра публичного сервиса —
«разные аккаунты видят общие данные»). Авторизация — через DEV_MODE +
X-Dev-User (см. api/deps/auth.require_user), как в остальных API-тестах.

Owner пишется из require_user на создании; пользовательские выборки фильтруют
по нему; строки без владельца (user_id IS NULL) не видны никому.
"""

from __future__ import annotations

import itertools

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from api.deps.db import get_session
from api.deps.queue import get_publisher, get_task_queue
from api.main import app
from core.config import get_settings
from core.repositories.account import AccountRepository
from core.schemas.account import AccountCreate

_PHONE = itertools.count(60_000_000_000)

USER_A = {"X-Dev-User": "111"}
USER_B = {"X-Dev-User": "222"}


def _next_phone() -> str:
    return f"+{next(_PHONE)}"


class _SpyTaskQueue:
    async def enqueue(self, task_name, *args, **kwargs):
        return "job-1"


@pytest.fixture
def dev_mode(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    # Аккаунты без прокси — чтобы не тянуть owner-прокси в каждый тест.
    monkeypatch.setenv("ALLOW_NO_PROXY", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(session, dev_mode):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_task_queue] = lambda: _SpyTaskQueue()
    app.dependency_overrides[get_publisher] = lambda: None
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# --- Аккаунты ----------------------------------------------------------------


def test_create_account_stamps_owner_and_isolates_list(client):
    # User A создаёт аккаунт.
    resp = client.post("/accounts", json={"phone": _next_phone()}, headers=USER_A)
    assert resp.status_code == 201, resp.text
    acc_a = resp.json()["id"]

    # User B создаёт свой.
    resp = client.post("/accounts", json={"phone": _next_phone()}, headers=USER_B)
    assert resp.status_code == 201, resp.text
    acc_b = resp.json()["id"]

    # Каждый видит только свой в списке.
    ids_a = {a["id"] for a in client.get("/accounts", headers=USER_A).json()}
    ids_b = {a["id"] for a in client.get("/accounts", headers=USER_B).json()}
    assert acc_a in ids_a and acc_b not in ids_a
    assert acc_b in ids_b and acc_a not in ids_b


def test_get_and_delete_other_users_account_is_404(client):
    acc_a = client.post("/accounts", json={"phone": _next_phone()}, headers=USER_A).json()["id"]

    # User B не может ни прочитать, ни удалить чужой аккаунт.
    assert client.get(f"/accounts/{acc_a}", headers=USER_B).status_code == 404
    assert client.delete(f"/accounts/{acc_a}", headers=USER_B).status_code == 404
    assert client.patch(
        f"/accounts/{acc_a}", json={"first_name": "x"}, headers=USER_B
    ).status_code == 404

    # А владелец — может прочитать.
    assert client.get(f"/accounts/{acc_a}", headers=USER_A).status_code == 200


def test_legacy_ownerless_account_invisible_to_everyone(client, session):
    # Строка без владельца (легаси до миграции) — не видна никому.
    orphan = AccountRepository(session).create(
        AccountCreate(
            phone=_next_phone(),
            user_id=None,
            session_enc=b"enc",
            device_model="iPhone15,3",
            system_version="17.5.1",
            app_version="10.14.5",
            lang_code="uk",
            system_lang_code="uk-UA",
        )
    )
    session.commit()

    for headers in (USER_A, USER_B):
        ids = {a["id"] for a in client.get("/accounts", headers=headers).json()}
        assert orphan.id not in ids
        assert client.get(f"/accounts/{orphan.id}", headers=headers).status_code == 404


def test_export_sessions_skips_other_users_accounts(client):
    acc_a = client.post("/accounts", json={"phone": _next_phone()}, headers=USER_A).json()["id"]
    # User B просит экспорт чужого id — получает пустой список (не 500/не утечка).
    resp = client.post(
        "/accounts/export-sessions", json={"account_ids": [acc_a]}, headers=USER_B
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_health_check_bulk_rejects_other_users_accounts(client):
    acc_a = client.post("/accounts", json={"phone": _next_phone()}, headers=USER_A).json()["id"]
    resp = client.post(
        "/accounts/health/check-bulk",
        json={"account_ids": [acc_a]},
        headers=USER_B,
    )
    assert resp.status_code == 422  # «неизвестные» id — чужой не раскрывается


# --- Персоны -----------------------------------------------------------------


def test_persona_isolation(client):
    pa = client.post("/personas", json={"name": "A"}, headers=USER_A).json()["id"]
    pb = client.post("/personas", json={"name": "B"}, headers=USER_B).json()["id"]

    ids_a = {p["id"] for p in client.get("/personas", headers=USER_A).json()}
    ids_b = {p["id"] for p in client.get("/personas", headers=USER_B).json()}
    assert pa in ids_a and pb not in ids_a
    assert pb in ids_b and pa not in ids_b

    assert client.get(f"/personas/{pa}", headers=USER_B).status_code == 404
    assert client.delete(f"/personas/{pa}", headers=USER_B).status_code == 404
    assert client.get(f"/personas/{pa}", headers=USER_A).status_code == 200


# --- Прокси ------------------------------------------------------------------


def _make_proxy(client, headers) -> int:
    resp = client.post(
        "/proxies",
        json={"host": "10.0.0.1", "port": 1080, "type": "socks5", "geo": "UA"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_proxy_isolation(client):
    pa = _make_proxy(client, USER_A)
    pb = _make_proxy(client, USER_B)

    ids_a = {p["id"] for p in client.get("/proxies", headers=USER_A).json()}
    ids_b = {p["id"] for p in client.get("/proxies", headers=USER_B).json()}
    assert pa in ids_a and pb not in ids_a
    assert pb in ids_b and pa not in ids_b

    assert client.get(f"/proxies/{pa}", headers=USER_B).status_code == 404
    assert client.delete(f"/proxies/{pa}", headers=USER_B).status_code == 404
    # Пул/автопик тоже только свои.
    pool_b = {p["id"] for p in client.get("/proxies/pool", headers=USER_B).json()}
    assert pa not in pool_b


def test_cannot_attach_other_users_proxy_on_account_create(client):
    # User A создаёт прокси; User B пытается создать аккаунт с ним → 422.
    pa = _make_proxy(client, USER_A)
    resp = client.post(
        "/accounts", json={"phone": _next_phone(), "proxy_id": pa}, headers=USER_B
    )
    assert resp.status_code == 422
