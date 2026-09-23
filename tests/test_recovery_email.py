"""Тесты recovery-email flow для 2FA (этап 7, backlog #1).

Без реального Telegram: моки Telethon-объектов Password / EmailUnconfirmedError /
ConfirmPasswordEmailRequest — проверяем что наш скелет корректно вызывает
raw-функции и правильно раскладывает состояние по meta.
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from core.config import get_settings
from core.crypto import encrypt_password
from core.models import Account
from worker.tasks.security import (
    confirm_recovery_email_impl,
    request_recovery_email_impl,
)

pytestmark = pytest.mark.asyncio

_TABLES = (
    "autopilot_actions",
    "autopilot_goals",
    "bulk_job_items",
    "bulk_jobs",
    "accounts",
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from core.crypto import reset_cache
    reset_cache()
    get_settings.cache_clear()
    yield
    reset_cache()
    get_settings.cache_clear()


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _make_account(session):
    a = Account(
        phone="+79990000001",
        session_enc=b"enc",
        status="pool",
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    session.add(a)
    session.flush()
    session.commit()
    return a.id


class _Ctx:
    def __init__(self, s):
        self._s = s

    def __enter__(self):
        return self._s

    def __exit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, client):
        self._client = client
        self.gets = 0
        self.releases = 0

    async def get(self, account_id):
        self.gets += 1
        return self._client

    async def release(self, account_id):
        self.releases += 1


def _make_ctx(session, client):
    return {
        "session_factory": lambda: _Ctx(session),
        "publisher": None,
        "client_pool": _FakePool(client),
    }


def _encrypted_password(plaintext: str) -> str:
    enc = encrypt_password(plaintext.encode("utf-8"))
    return base64.b64encode(enc).decode("ascii")


# ── request_recovery_email_impl ───────────────────────────────────────────


async def test_request_bad_password_enc_reports_error(session):
    _clean(session)
    account_id = _make_account(session)
    client = MagicMock()
    result = await request_recovery_email_impl(
        _make_ctx(session, client),
        account_id,
        "user@example.com",
        "not-base64-fernet",
    )
    assert result["ok"] is False
    assert result["reason"] == "bad_password_enc"


async def test_request_pending_saves_email_to_meta(session, monkeypatch):
    """Настоящий Telegram отвечает EmailUnconfirmedError → сохраняем pending."""
    _clean(session)
    account_id = _make_account(session)

    async def fake_request_email_setup(_client, *, current_password, new_email, **_kwargs):
        from worker.security.recovery_email import EmailPending
        assert current_password == "hunter2"
        assert new_email == "user@example.com"
        return EmailPending(email=new_email, code_length=6)

    # Мокаем helper: proxy для _request_email_setup внутри task.
    import worker.tasks.security as sec_task
    monkeypatch.setattr(sec_task, "request_email_setup", fake_request_email_setup)

    client = MagicMock()
    result = await request_recovery_email_impl(
        _make_ctx(session, client),
        account_id,
        "user@example.com",
        _encrypted_password("hunter2"),
    )
    assert result == {"ok": True, "state": "pending", "code_length": 6}

    # accounts.meta теперь содержит pending.
    session.expire_all()
    account = session.get(Account, account_id)
    pending = account.meta["recovery_email_pending"]
    assert pending["email"] == "user@example.com"
    assert pending["code_length"] == 6
    assert "requested_at" in pending
    # confirmed поле ещё не выставлено:
    assert "recovery_email" not in account.meta


async def test_request_no_2fa_reports_reason(session, monkeypatch):
    _clean(session)
    account_id = _make_account(session)

    from worker.security.recovery_email import NoPasswordSetError

    async def fake(_client, **_kwargs):
        raise NoPasswordSetError("no 2fa")

    import worker.tasks.security as sec_task
    monkeypatch.setattr(sec_task, "request_email_setup", fake)

    client = MagicMock()
    result = await request_recovery_email_impl(
        _make_ctx(session, client), account_id,
        "user@example.com", _encrypted_password("x"),
    )
    assert result == {"ok": False, "reason": "no_2fa"}

    # meta НЕ должна получить pending.
    session.expire_all()
    account = session.get(Account, account_id)
    assert "recovery_email_pending" not in (account.meta or {})


async def test_request_bad_password_reports_reason(session, monkeypatch):
    _clean(session)
    account_id = _make_account(session)

    from worker.security.recovery_email import BadCurrentPasswordError

    async def fake(_client, **_kwargs):
        raise BadCurrentPasswordError("wrong")

    import worker.tasks.security as sec_task
    monkeypatch.setattr(sec_task, "request_email_setup", fake)

    client = MagicMock()
    result = await request_recovery_email_impl(
        _make_ctx(session, client), account_id,
        "user@example.com", _encrypted_password("wrong"),
    )
    assert result["ok"] is False
    assert result["reason"] == "bad_password"


async def test_request_auto_confirmed_when_code_length_zero(session, monkeypatch):
    """Редкий путь: Telegram принял email без confirmation → сразу confirmed."""
    _clean(session)
    account_id = _make_account(session)

    async def fake_setup(_client, *, current_password, new_email, **_kwargs):
        from worker.security.recovery_email import EmailPending
        return EmailPending(email=new_email, code_length=0)

    import worker.tasks.security as sec_task
    monkeypatch.setattr(sec_task, "request_email_setup", fake_setup)

    client = MagicMock()
    result = await request_recovery_email_impl(
        _make_ctx(session, client), account_id,
        "user@example.com", _encrypted_password("hunter2"),
    )
    assert result == {"ok": True, "state": "confirmed", "code_length": 0}

    session.expire_all()
    account = session.get(Account, account_id)
    assert account.meta["recovery_email"] == "user@example.com"
    assert "recovery_email_pending" not in account.meta
    assert "recovery_email_confirmed_at" in account.meta


# ── confirm_recovery_email_impl ────────────────────────────────────────────


async def test_confirm_without_pending_reports_no_pending(session):
    _clean(session)
    account_id = _make_account(session)

    client = MagicMock()
    result = await confirm_recovery_email_impl(
        _make_ctx(session, client), account_id, "123456"
    )
    assert result == {"ok": False, "reason": "no_pending"}


async def test_confirm_success_promotes_pending_to_confirmed(session, monkeypatch):
    _clean(session)
    account_id = _make_account(session)

    # Ставим pending вручную.
    account = session.get(Account, account_id)
    account.meta = {
        "recovery_email_pending": {
            "email": "user@example.com",
            "code_length": 6,
            "requested_at": "2026-09-22T10:00:00+00:00",
        }
    }
    session.commit()

    fake_confirm = AsyncMock(return_value=None)
    import worker.tasks.security as sec_task
    monkeypatch.setattr(sec_task, "confirm_email_code", fake_confirm)

    client = MagicMock()
    result = await confirm_recovery_email_impl(
        _make_ctx(session, client), account_id, "123456"
    )
    assert result["ok"] is True
    assert result["state"] == "confirmed"
    assert result["email"] == "user@example.com"
    fake_confirm.assert_called_once()

    session.expire_all()
    account = session.get(Account, account_id)
    assert account.meta["recovery_email"] == "user@example.com"
    assert "recovery_email_pending" not in account.meta


async def test_confirm_bad_code_keeps_pending(session, monkeypatch):
    _clean(session)
    account_id = _make_account(session)
    account = session.get(Account, account_id)
    account.meta = {
        "recovery_email_pending": {
            "email": "user@example.com",
            "code_length": 6,
            "requested_at": "2026-09-22T10:00:00+00:00",
        }
    }
    session.commit()

    async def fake_confirm(**_kwargs):
        # Имитация Telethon errors.CodeInvalidError.
        raise Exception("CODE_INVALID")

    import worker.tasks.security as sec_task
    monkeypatch.setattr(sec_task, "confirm_email_code", fake_confirm)

    client = MagicMock()
    result = await confirm_recovery_email_impl(
        _make_ctx(session, client), account_id, "wrong"
    )
    assert result["ok"] is False
    assert result["reason"] == "code_invalid"

    # meta pending остался — можно попробовать ещё раз.
    session.expire_all()
    account = session.get(Account, account_id)
    assert account.meta.get("recovery_email_pending") is not None
    assert "recovery_email" not in account.meta


# ── recovery_email helper: SRP path is exercised through task tests via mocks;
# real Telethon-call test would require full Telegram testnet — вне scope MVP.
