"""verify_and_enrich_session: валидация импортированной сессии + подтягивание
профиля.

Тестируем ТОЛЬКО сервисную функцию (без FastAPI-клиента) — так нам не нужен
живой Telethon или мок HTTP: мокаем worker.profiles.sync_profile_impl
напрямую. Логика раскладки ошибок: fatal-типы (AuthKeyUnregisteredError и
т.п.) → откат аккаунта + SessionNotAuthorizedError; прочие (сеть/таймаут) →
аккаунт остаётся, возвращаем {"verified": False, ...}.

Дополнительно проверяем, что модификация sync_profile_impl в этом же PR
(подмена псевдо-телефона на настоящий из get_me) реально заменяет phone.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from api.services import accounts as accounts_service
from core.enums import AccountStatus
from core.models import Account

pytestmark = pytest.mark.asyncio


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


def _make_account(session, phone: str = "+70000000001") -> int:
    acc = Account(
        phone=phone,
        session_enc=b"enc",
        status=AccountStatus.POOL.value,
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    session.add(acc)
    session.commit()
    return acc.id


def _clean(session):
    session.execute(text("TRUNCATE accounts, health_events, account_status_history RESTART IDENTITY CASCADE"))
    session.commit()


async def test_verify_ok_marks_verified_true(session):
    _clean(session)
    aid = _make_account(session)
    with patch.object(
        accounts_service, "verify_and_enrich_session", wraps=accounts_service.verify_and_enrich_session
    ):
        # Мокаем sync_profile_impl там, где он реально вызывается — внутри функции.
        with patch(
            "worker.profiles.sync.sync_profile_impl",
            new=AsyncMock(return_value={"account_id": aid, "has_2fa": False, "username": "x"}),
        ):
            result = await accounts_service.verify_and_enrich_session(_factory(session), account_id=aid)
    assert result == {"verified": True}


async def test_fatal_error_deletes_account_and_raises(session):
    """Телетон упал AuthKeyUnregisteredError → аккаунт удаляется, бросаем
    SessionNotAuthorizedError с человеко-читаемым текстом."""
    _clean(session)
    aid = _make_account(session)

    # Поддельное исключение именно с нужным именем класса.
    class AuthKeyUnregisteredError(Exception):
        pass

    with patch(
        "worker.profiles.sync.sync_profile_impl",
        new=AsyncMock(side_effect=AuthKeyUnregisteredError("key gone")),
    ):
        with pytest.raises(accounts_service.SessionNotAuthorizedError) as ctx:
            await accounts_service.verify_and_enrich_session(_factory(session), account_id=aid)

    # Аккаунт точно удалён.
    assert session.query(Account).filter(Account.id == aid).first() is None
    # Сообщение упоминает конкретный тип + совет.
    assert "AuthKeyUnregisteredError" in str(ctx.value)


async def test_transient_network_error_keeps_account(session):
    """Любое НЕ-fatal исключение — таймаут, сетевой сбой и т.п. — не удаляет
    аккаунт: пользователь нажмёт «Обновить» позже. Возвращаем verified=False."""
    _clean(session)
    aid = _make_account(session)

    with patch(
        "worker.profiles.sync.sync_profile_impl",
        new=AsyncMock(side_effect=TimeoutError("socket timeout")),
    ):
        result = await accounts_service.verify_and_enrich_session(_factory(session), account_id=aid)

    assert result["verified"] is False
    assert "TimeoutError" in result["error"]
    # Аккаунт остался в БД.
    assert session.query(Account).filter(Account.id == aid).first() is not None


async def test_user_deactivated_error_also_fatal(session):
    """Удалённый аккаунт — fatal, откат как и при AuthKey."""
    _clean(session)
    aid = _make_account(session)

    class UserDeactivatedError(Exception):
        pass

    with patch(
        "worker.profiles.sync.sync_profile_impl",
        new=AsyncMock(side_effect=UserDeactivatedError("gone")),
    ):
        with pytest.raises(accounts_service.SessionNotAuthorizedError):
            await accounts_service.verify_and_enrich_session(_factory(session), account_id=aid)
    assert session.query(Account).filter(Account.id == aid).first() is None


# ── sync_profile_impl: подмена псевдо-телефона на настоящий ─────────────────


class _FakeClient:
    """Минимальный Telethon-клиент для sync_profile — только то, что он дергает."""

    def __init__(self, me):
        self._me = me

    async def connect(self):
        return None

    async def get_me(self):
        return self._me

    async def get_entity(self, _target):
        raise RuntimeError("bio skip")

    async def download_profile_photo(self, *_a, **_kw):
        return None

    async def __call__(self, _request):
        # Для GetPasswordRequest — вернём объект с has_password=False.
        from types import SimpleNamespace

        return SimpleNamespace(has_password=False)


class _FakePool:
    def __init__(self, client):
        self._client = client

    async def get(self, _aid):
        return self._client

    async def release(self, _aid):
        return None


async def test_sync_profile_replaces_pseudo_phone_with_real_one(session):
    """Если на аккаунте стоит псевдо-номер (из импорта .session: «ses…» —
    без «+»), а get_me вернул настоящий — заменяем. Это решает баг-репорт
    «вместо номера в UI было ses1a2b…»."""
    _clean(session)
    pseudo = "sesdeadbeef12345678"
    aid = _make_account(session, phone=pseudo)

    from types import SimpleNamespace
    from worker.profiles import sync as sync_mod

    me = SimpleNamespace(
        first_name="Иван", last_name="Петров", username="vanya",
        photo=None, premium=False, phone="79001234567",
    )
    client = _FakeClient(me)
    ctx = {"session_factory": _factory(session), "client_pool": _FakePool(client), "publisher": None}
    out = await sync_mod.sync_profile_impl(ctx, aid)
    assert out["username"] == "vanya"

    updated = session.query(Account).filter(Account.id == aid).first()
    # Псевдо-номер заменён на настоящий с «+».
    assert updated.phone == "+79001234567"
    assert updated.first_name == "Иван"


async def test_sync_profile_keeps_real_phone_entered_by_user(session):
    """Если на аккаунте уже настоящий номер (начинается с «+»), не трогаем
    его — даже если get_me вернул другой (сомнительный кейс, но лучше
    перебдеть, чем перезаписать номер, который юзер ввёл сам)."""
    _clean(session)
    aid = _make_account(session, phone="+70000000001")

    from types import SimpleNamespace
    from worker.profiles import sync as sync_mod

    me = SimpleNamespace(
        first_name="X", last_name=None, username=None, photo=None,
        premium=False, phone="79999999999",
    )
    client = _FakeClient(me)
    ctx = {"session_factory": _factory(session), "client_pool": _FakePool(client), "publisher": None}
    await sync_mod.sync_profile_impl(ctx, aid)

    updated = session.query(Account).filter(Account.id == aid).first()
    assert updated.phone == "+70000000001"  # не изменился
    assert updated.first_name == "X"
