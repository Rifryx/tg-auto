"""Acceptance-тесты shared API (PROJECT-STAGES §6/§10).

БД настоящая (тестовый Postgres из conftest), очередь — spy (никакого Redis и
Telethon). Авторизация в большинстве тестов через DEV_MODE + заголовок
X-Dev-User; отдельный тест проверяет 401 вне DEV_MODE.
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
from core.enums import ProxyType
from core.repositories.account import AccountRepository
from core.repositories.account_status_history import AccountStatusHistoryRepository
from core.repositories.proxy import ProxyRepository
from core.schemas.account import AccountCreate
from core.schemas.proxy import ProxyCreate
from core.queue.task_names import TaskName

_PHONE = itertools.count(50_000_000_000)
_DEV_HEADERS = {"X-Dev-User": "42"}


def _next_phone() -> str:
    return f"+{next(_PHONE)}"


class _SpyTaskQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple] = []

    async def enqueue(self, task_name, *args, **kwargs):
        self.enqueued.append((task_name, args, kwargs))
        return "job-1"


@pytest.fixture
def dev_mode(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(session):
    """TestClient с подменённой сессией и spy-очередью."""
    spy = _SpyTaskQueue()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_task_queue] = lambda: spy
    app.dependency_overrides[get_publisher] = lambda: None
    client = TestClient(app)
    client.spy_queue = spy  # type: ignore[attr-defined]
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _make_proxy(session, geo: str = "UA") -> int:
    proxy = ProxyRepository(session).create(
        ProxyCreate(host="10.0.0.1", port=1080, type=ProxyType.SOCKS5, geo=geo)
    )
    session.commit()
    return proxy.id


def _make_account(session, status: str = "created") -> int:
    account = AccountRepository(session).create(
        AccountCreate(
            phone=_next_phone(),
            session_enc=b"enc",
            device_model="iPhone15,3",
            system_version="17.5.1",
            app_version="10.14.5",
            lang_code="uk",
            system_lang_code="uk-UA",
        )
    )
    if status != "created":
        account.status = status
    session.commit()
    return account.id


# --- 1. OpenAPI + health ------------------------------------------------------


def test_openapi_documents_all_routes():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}

    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    for expected in [
        "/accounts",
        "/accounts/{account_id}",
        "/accounts/{account_id}/warming",
        "/accounts/{account_id}/history",
        "/accounts/{account_id}/actions/retire",
        "/accounts/{account_id}/actions/acknowledge_ban",
        "/proxies",
        "/proxies/{proxy_id}",
        "/proxies/{proxy_id}/check",
        "/personas",
        "/personas/{persona_id}",
    ]:
        assert expected in paths, expected


# --- 2. 401 без initData вне DEV_MODE -----------------------------------------


def test_requires_auth_without_dev_mode(session, monkeypatch):
    monkeypatch.setenv("DEV_MODE", "false")
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 44)
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    get_settings.cache_clear()
    app.dependency_overrides[get_session] = lambda: session
    try:
        resp = TestClient(app).get("/accounts")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


# --- 3. POST /accounts: фингерпринт + login_start в очереди -------------------


def test_create_account_generates_fingerprint_and_enqueues_login(dev_mode, client, session):
    proxy_id = _make_proxy(session, geo="UA")

    resp = client.post(
        "/accounts",
        json={"phone": _next_phone(), "proxy_id": proxy_id},
        headers=_DEV_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()

    # фингерпринт сгенерирован (непустые поля), гео → язык из прокси (UA)
    assert data["device_model"]
    assert data["system_version"]
    assert data["lang_code"] == "uk"
    assert data["status"] == "created"
    assert data["proxy_id"] == proxy_id

    # login_start положен в очередь ровно с id аккаунта
    assert client.spy_queue.enqueued == [(TaskName.ACCOUNT_LOGIN_START, (data["id"],), {})]

    # запись реально в БД
    assert AccountRepository(session).get(data["id"]) is not None


# --- 4. PATCH с фингерпринт-полем → 422 --------------------------------------


def test_patch_account_rejects_fingerprint_field(dev_mode, client):
    resp = client.patch(
        "/accounts/1", json={"device_model": "hacked"}, headers=_DEV_HEADERS
    )
    assert resp.status_code == 422


# --- 5. Действие retire идёт через state machine -----------------------------


def test_retire_action_transitions_and_writes_history(dev_mode, client, session):
    account_id = _make_account(session, status="created")

    resp = client.post(
        f"/accounts/{account_id}/actions/retire", headers=_DEV_HEADERS
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "retired"

    # статус в БД и запись в истории
    assert AccountRepository(session).get(account_id).status == "retired"
    history = AccountStatusHistoryRepository(session).list_by_account(account_id)
    assert any(h.to_status == "retired" and h.reason == "account.retire" for h in history)
