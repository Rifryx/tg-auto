"""Acceptance-тесты логин-флоу (PROJECT-STAGES §3.2/§11).

Реальный логин запрещён: ``TelegramClient`` подменяется фейком через
``ClientPool(client_factory=...)`` — сам пул, state machine, крипто настоящие.
БД не нужна: fake-сессия поверх общего in-memory стора обслуживает репозитории и
state machine (get/add/flush/commit), а объект ``Account`` переживает шаги флоу.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from telethon.errors import (
    FloodWaitError as TelethonFloodWaitError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

import worker.tasks.dispatch as dispatch
from telethon.crypto import AuthKey
from telethon.sessions import StringSession
from core.crypto import decrypt_session, encrypt_session, reset_cache
from core.config import get_settings
from core.models import Account, AccountStatusHistory, Proxy
from worker.client_pool import ClientPool
from worker.login import (
    LOGIN_CHANNEL,
    login_confirm_impl,
    login_password_impl,
    login_start_impl,
)
from worker.tasks import login_start as login_start_task

pytestmark = pytest.mark.asyncio

_SETTINGS = SimpleNamespace(telegram_api_id=1, telegram_api_hash="hash")


def _valid_session_string() -> str:
    """Настоящая (по формату) StringSession — ClientPool умеет её распарсить."""
    ss = StringSession()
    ss.set_dc(2, "149.154.167.51", 443)
    ss.auth_key = AuthKey(b"\x00" * 256)
    return ss.save()


_SAVED_SESSION = _valid_session_string()


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DEV_MODE", "true")
    reset_cache()
    get_settings.cache_clear()
    try:
        yield
    finally:
        reset_cache()
        get_settings.cache_clear()


# --- Fake DB (общий стор, переживающий шаги) ---------------------------------


class _FakeSession:
    def __init__(self, store: dict) -> None:
        self._store = store

    def get(self, model, id_):
        if model is Account:
            return self._store["accounts"].get(id_)
        if model is Proxy:
            return self._store["proxies"].get(id_)
        return None

    def add(self, obj) -> None:
        if isinstance(obj, AccountStatusHistory):
            self._store["history"].append(obj)

    def flush(self) -> None:  # noqa: D401 - no-op для fake
        pass

    def commit(self) -> None:
        pass


def _make_store():
    proxy = Proxy(
        id=7, host="10.0.0.1", port=1080, login=None, password_enc=None,
        type="socks5", status="alive",
    )
    account = Account(
        id=1,
        phone="+10000000001",
        session_enc=encrypt_session(b""),  # пустая StringSession
        proxy_id=7,
        status="created",
        meta={},
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    return {"accounts": {1: account}, "proxies": {7: proxy}, "history": []}


def _session_factory(store: dict):
    class _Ctx:
        def __enter__(self):
            return _FakeSession(store)

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


# --- Spy publisher ------------------------------------------------------------


class _SpyPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def publish(self, channel: str, payload) -> None:
        self.events.append((channel, dict(payload)))

    def login_events(self) -> list[dict]:
        return [p for ch, p in self.events if ch == LOGIN_CHANNEL]


# --- Fake TelegramClient factory ---------------------------------------------


class _Req:
    pass


def _make_client_factory(
    *,
    phone_code_hash: str = "HASH123",
    save_value: str = _SAVED_SESSION,
    on_send=None,
    on_signin_code=None,
    on_signin_password=None,
):
    def factory(*args, **kwargs):
        client = SimpleNamespace()
        client.session = SimpleNamespace(save=lambda: save_value)
        client.connect = AsyncMock()
        client.disconnect = AsyncMock()

        async def send_code_request(phone):
            if on_send is not None:
                return on_send(phone)
            return SimpleNamespace(phone_code_hash=phone_code_hash)

        async def sign_in(**kw):
            if "password" in kw:
                if on_signin_password is not None:
                    return on_signin_password(kw)
                return SimpleNamespace()
            if on_signin_code is not None:
                return on_signin_code(kw)
            return SimpleNamespace()

        client.send_code_request = send_code_request
        client.sign_in = sign_in
        return client

    return factory


def _ctx(store, publisher, factory):
    pool = ClientPool(_session_factory(store), settings=_SETTINGS, client_factory=factory)
    return {
        "session_factory": _session_factory(store),
        "publisher": publisher,
        "client_pool": pool,
        "redis": None,
    }


# --- 1. Код без 2FA -----------------------------------------------------------


async def test_code_without_2fa():
    store = _make_store()
    pub = _SpyPublisher()
    ctx = _ctx(store, pub, _make_client_factory())

    await login_start_impl(ctx, 1)
    assert pub.login_events()[-1] == {"account_id": 1, "state": "waiting_code"}
    assert store["accounts"][1].meta["phone_code_hash"] == "HASH123"

    await login_confirm_impl(ctx, 1, "12345")

    account = store["accounts"][1]
    assert decrypt_session(account.session_enc).decode() == _SAVED_SESSION
    assert account.status == "warming"
    assert pub.login_events()[-1] == {"account_id": 1, "state": "success"}


# --- 2. С 2FA -----------------------------------------------------------------


async def test_with_2fa():
    def raise_spn(kw):
        raise SessionPasswordNeededError(request=_Req())

    store = _make_store()
    pub = _SpyPublisher()
    ctx = _ctx(store, pub, _make_client_factory(on_signin_code=raise_spn))

    await login_start_impl(ctx, 1)
    assert pub.login_events()[-1]["state"] == "waiting_code"

    await login_confirm_impl(ctx, 1, "12345")
    assert pub.login_events()[-1] == {"account_id": 1, "state": "waiting_password"}
    assert store["accounts"][1].status == "created"  # ещё не warming

    await login_password_impl(ctx, 1, "s3cret")
    assert store["accounts"][1].status == "warming"
    assert pub.login_events()[-1] == {"account_id": 1, "state": "success"}


# --- 3. Неверный код ----------------------------------------------------------


async def test_invalid_code():
    def raise_invalid(kw):
        raise PhoneCodeInvalidError(request=_Req())

    store = _make_store()
    pub = _SpyPublisher()
    ctx = _ctx(store, pub, _make_client_factory(on_signin_code=raise_invalid))

    await login_start_impl(ctx, 1)
    await login_confirm_impl(ctx, 1, "00000")

    last = pub.login_events()[-1]
    assert last["state"] == "failed"
    assert last["reason"] == "код неверный"
    assert store["accounts"][1].status == "created"


# --- 4. Флудвейт --------------------------------------------------------------


async def test_flood_wait_reschedules(monkeypatch):
    scheduled: list[tuple] = []

    class _SpyTaskQueue:
        def __init__(self, redis=None, queue=None):
            pass

        async def schedule(self, name, run_at, *args, **kwargs):
            scheduled.append((name, run_at, args, kwargs))
            return "job-1"

    monkeypatch.setattr(dispatch, "TaskQueue", _SpyTaskQueue)

    def raise_flood(phone):
        raise TelethonFloodWaitError(request=_Req(), capture=30)

    store = _make_store()
    pub = _SpyPublisher()
    ctx = _ctx(store, pub, _make_client_factory(on_send=raise_flood))

    # Вызываем обёрнутую задачу — FloodWait ловит middleware диспетчера.
    await login_start_task(ctx, 1)

    assert len(scheduled) == 1
    name, run_at, args, kwargs = scheduled[0]
    assert name == "account.login_start"
    assert args == (1,)
    assert store["accounts"][1].status == "created"
    assert "phone_code_hash" not in store["accounts"][1].meta


# --- 5. confirm без login_start (нет pending) --------------------------------


async def test_confirm_without_pending():
    store = _make_store()
    pub = _SpyPublisher()
    ctx = _ctx(store, pub, _make_client_factory())

    await login_confirm_impl(ctx, 1, "12345")

    last = pub.login_events()[-1]
    assert last["state"] == "failed"
    assert last["reason"] == "no pending login"
    assert store["accounts"][1].status == "created"
