"""Acceptance-тесты жизненного цикла ClientPool (PROJECT-STAGES §3.1).

Telethon замокан полностью — реальный ``TelegramClient`` не создаётся и логин не
выполняется. БД не требуется: используется лёгкая fake-сессия, реализующая
единственный нужный репозиториям метод ``get(model, id_)``. Крипто — настоящее
(round-trip через Fernet), чтобы проверить расшифровку сессии и пароля прокси.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

import worker.client_pool.pool as pool_module
from core.config import get_settings
from core.crypto import encrypt_password, encrypt_session, reset_cache
from core.models import Account, Proxy
from worker.client_pool import AccountUnavailableError, ClientPool

pytestmark = pytest.mark.asyncio


# --- Окружение: валидный ключ шифрования для настоящего Fernet ----------------


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    # ``core.crypto`` дергает ``get_settings()`` целиком, поэтому конфиг должен
    # быть валиден: DEV_MODE снимает требования Telegram/LLM-кредов, а нам от
    # настроек нужен только ``encryption_key`` для Fernet.
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DEV_MODE", "true")
    reset_cache()
    get_settings.cache_clear()
    try:
        yield
    finally:
        reset_cache()
        get_settings.cache_clear()


# --- Fake-слой БД -------------------------------------------------------------


class _FakeSession:
    """Минимальная сессия: только ``get(model, id_)``, как нужно репозиториям."""

    def __init__(self, accounts: dict, proxies: dict) -> None:
        self._by_model = {Account: accounts, Proxy: proxies}

    def get(self, model, id_):
        return self._by_model[model].get(id_)


class _SessionCtx:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __enter__(self) -> _FakeSession:
        return self._session

    def __exit__(self, *exc) -> bool:
        return False


def _session_factory(accounts: dict, proxies: dict):
    return lambda: _SessionCtx(_FakeSession(accounts, proxies))


# --- Spy-клиент Telethon ------------------------------------------------------


class _SpyClient:
    """Замена ``TelegramClient``: запоминает аргументы конструктора."""

    instances: list["_SpyClient"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.disconnect = AsyncMock()
        _SpyClient.instances.append(self)


@pytest.fixture
def spy_client(monkeypatch):
    _SpyClient.instances = []
    monkeypatch.setattr(pool_module, "TelegramClient", _SpyClient)
    return _SpyClient


_SETTINGS = SimpleNamespace(telegram_api_id=424242, telegram_api_hash="api-hash-xyz")


# --- Фабрики данных -----------------------------------------------------------


def _make_proxy(proxy_id: int = 7) -> Proxy:
    return Proxy(
        id=proxy_id,
        host="10.0.0.1",
        port=1080,
        login="proxyuser",
        password_enc=encrypt_password(b"proxypass"),
        type="socks5",
        status="alive",
    )


def _make_account(
    account_id: int = 1,
    *,
    status: str = "pool",
    proxy_id: int | None = 7,
) -> Account:
    return Account(
        id=account_id,
        phone=f"+{10_000_000_000 + account_id}",
        session_enc=encrypt_session(b""),  # валидная пустая StringSession
        proxy_id=proxy_id,
        status=status,
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )


def _pool(accounts: dict, proxies: dict, spy=None) -> ClientPool:
    return ClientPool(
        _session_factory(accounts, proxies),
        settings=_SETTINGS,
    )


# --- 1. Переиспользование инстанса и выключение при release -------------------


async def test_get_twice_returns_same_instance_and_release_disconnects(spy_client):
    account = _make_account()
    proxy = _make_proxy()
    pool = _pool({1: account}, {7: proxy})

    first = await pool.get(1)
    second = await pool.get(1)

    assert first is second
    assert len(spy_client.instances) == 1  # клиент создан ровно один раз

    # refcount == 2 → первый release не выключает клиент
    await pool.release(1)
    first.disconnect.assert_not_awaited()

    # второй release обнуляет refcount → disconnect
    await pool.release(1)
    first.disconnect.assert_awaited_once()


# --- 2. Фингерпринт в конструктор передаётся из аккаунта, а не дефолты ---------


async def test_constructor_receives_account_fingerprint(spy_client):
    account = _make_account()
    proxy = _make_proxy()
    pool = _pool({1: account}, {7: proxy})

    await pool.get(1)

    (spy,) = spy_client.instances
    assert spy.kwargs["device_model"] == "iPhone15,3"
    assert spy.kwargs["system_version"] == "17.5.1"
    assert spy.kwargs["app_version"] == "10.14.5"
    assert spy.kwargs["lang_code"] == "uk"
    assert spy.kwargs["system_lang_code"] == "uk-UA"
    # api creds и ретраи тоже переданы явно
    assert spy.args[1:] == (424242, "api-hash-xyz")
    assert spy.kwargs["connection_retries"] == 3
    assert spy.kwargs["request_retries"] == 3
    # прокси в формате (type, host, port, username, password)
    assert spy.kwargs["proxy"] == ("socks5", "10.0.0.1", 1080, "proxyuser", "proxypass")


# --- 3. banned → AccountUnavailableError, клиент не создаётся ------------------


async def test_banned_account_raises_and_no_client_created(spy_client):
    account = _make_account(status="banned")
    proxy = _make_proxy()
    pool = _pool({1: account}, {7: proxy})

    with pytest.raises(AccountUnavailableError):
        await pool.get(1)

    assert spy_client.instances == []


async def test_retired_account_raises(spy_client):
    account = _make_account(status="retired")
    pool = _pool({1: account}, {7: _make_proxy()})

    with pytest.raises(AccountUnavailableError):
        await pool.get(1)
    assert spy_client.instances == []


# --- 4. Аккаунт без proxy_id → понятный RuntimeError --------------------------


async def test_account_without_proxy_raises_runtime_error(spy_client):
    account = _make_account(proxy_id=None)
    pool = _pool({1: account}, {})

    with pytest.raises(RuntimeError, match="proxy"):
        await pool.get(1)
    assert spy_client.instances == []


# --- 5. close_all дисконнектит всё и очищает реестр ---------------------------


async def test_close_all_disconnects_everything_and_clears(spy_client):
    accounts = {1: _make_account(1), 2: _make_account(2)}
    proxies = {7: _make_proxy()}
    pool = _pool(accounts, proxies)

    c1 = await pool.get(1)
    c2 = await pool.get(2)
    assert len(spy_client.instances) == 2

    await pool.close_all()

    c1.disconnect.assert_awaited_once()
    c2.disconnect.assert_awaited_once()
    # реестр пуст: повторный get создаёт новый инстанс
    await pool.get(1)
    assert len(spy_client.instances) == 3
