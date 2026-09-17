"""Тесты bulk-action set_2fa (этап 7 УТП).

Постгрес нужен для persistence (accounts.two_factor_password_enc). Telethon
не поднимается — fake-клиент ловит ``edit_2fa`` и запоминает kwargs.
"""

from __future__ import annotations

import base64
import os

import pytest
from sqlalchemy import text

from core.crypto import decrypt_password, encrypt_password, reset_cache

# Валидный dev-ключ, чтобы модуль crypto поднимался без реальной инфры.
os.environ.setdefault("ENCRYPTION_KEY", "yWNCwxk9pQfP1Q9ONFvsUpP2QGyLBc5aQvj9k4vX_9M=")

from core.models import Account, AccountHealth
from core.repositories.account_health import AccountHealthRepository
from modules.bulk.actions.registry import ACTION_REGISTRY
from modules.bulk.actions.set_2fa import Set2FAPayload

pytestmark = pytest.mark.asyncio

_TABLES = (
    "bulk_job_items",
    "bulk_jobs",
    "accounts",
    "proxies",
    "health_events",
    "account_health",
    "account_status_history",
    "warming_activities",
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
)
_PHONE = iter(range(40_000_000_000, 40_001_000_000))


class _FakeClient:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._fail = fail

    async def edit_2fa(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self._fail is not None:
            raise self._fail
        return True


def _clean(session):
    reset_cache()
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


def _make_account(session, *, existing_2fa: str | None = None) -> int:
    enc = encrypt_password(existing_2fa.encode()) if existing_2fa else None
    acc = Account(
        phone=f"+{next(_PHONE)}",
        session_enc=b"enc",
        status="pool",
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
        two_factor_password_enc=enc,
    )
    session.add(acc)
    session.flush()
    session.commit()
    return acc.id


def _enc_b64(plain: str) -> str:
    return base64.b64encode(encrypt_password(plain.encode())).decode("ascii")


# ── set (не было 2FA) ────────────────────────────────────────────────────────


async def test_set_2fa_on_fresh_account_sets_password_and_flag(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient()
    action = ACTION_REGISTRY["set_2fa"]

    payload = Set2FAPayload(
        mode="set_or_change",
        password_enc_b64=_enc_b64("hunter2!"),
        hint="favorite thing",
    )
    result = await action.run(
        account_id=account_id,
        payload=payload,
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )

    assert result.ok is True
    assert client.calls[0]["current_password"] is None
    assert client.calls[0]["new_password"] == "hunter2!"

    session.expire_all()
    acc = session.get(Account, account_id)
    assert acc.two_factor_password_enc is not None
    assert decrypt_password(acc.two_factor_password_enc) == b"hunter2!"
    assert acc.two_factor_hint == "favorite thing"

    health = AccountHealthRepository(session).get(account_id)
    assert health is not None and health.has_2fa is True


# ── change (уже был 2FA) ─────────────────────────────────────────────────────


async def test_set_2fa_change_uses_current_password(session):
    _clean(session)
    account_id = _make_account(session, existing_2fa="old-pass")
    client = _FakeClient()
    action = ACTION_REGISTRY["set_2fa"]

    payload = Set2FAPayload(
        mode="set_or_change",
        password_enc_b64=_enc_b64("new-strong-1"),
    )
    await action.run(
        account_id=account_id,
        payload=payload,
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )

    assert client.calls[0]["current_password"] == "old-pass"
    assert client.calls[0]["new_password"] == "new-strong-1"

    session.expire_all()
    acc = session.get(Account, account_id)
    assert decrypt_password(acc.two_factor_password_enc) == b"new-strong-1"


# ── remove ───────────────────────────────────────────────────────────────────


async def test_set_2fa_remove_clears_password(session):
    _clean(session)
    account_id = _make_account(session, existing_2fa="old-pass")
    client = _FakeClient()
    action = ACTION_REGISTRY["set_2fa"]

    payload = Set2FAPayload(mode="remove")
    result = await action.run(
        account_id=account_id,
        payload=payload,
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.ok is True
    assert client.calls[0] == {"current_password": "old-pass", "new_password": None}

    session.expire_all()
    acc = session.get(Account, account_id)
    assert acc.two_factor_password_enc is None
    assert acc.two_factor_hint is None
    health = AccountHealthRepository(session).get(account_id)
    assert health is not None and health.has_2fa is False


# ── remove без установленного 2FA — SKIPPED ─────────────────────────────────


async def test_set_2fa_remove_when_no_2fa_is_skipped(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient()
    action = ACTION_REGISTRY["set_2fa"]

    result = await action.run(
        account_id=account_id,
        payload=Set2FAPayload(mode="remove"),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.ok is False
    assert result.skipped is True
    assert result.detail == {"reason": "no_2fa"}
    assert client.calls == []  # edit_2fa не звался


# ── edit_2fa падает → detail.reason=edit_2fa_failed, БД не меняется ─────────


async def test_set_2fa_persists_nothing_when_edit_fails(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient(fail=RuntimeError("wrong current"))
    action = ACTION_REGISTRY["set_2fa"]

    result = await action.run(
        account_id=account_id,
        payload=Set2FAPayload(
            mode="set_or_change",
            password_enc_b64=_enc_b64("boom"),
        ),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.ok is False
    assert result.detail["reason"] == "edit_2fa_failed"

    session.expire_all()
    acc = session.get(Account, account_id)
    assert acc.two_factor_password_enc is None
    health = AccountHealthRepository(session).get(account_id)
    # Пробы has_2fa не трогалась — snapshot либо не создан, либо None.
    assert health is None or health.has_2fa is None


# ── invalid password_enc_b64 → item failed ──────────────────────────────────


async def test_set_2fa_invalid_password_enc(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient()
    action = ACTION_REGISTRY["set_2fa"]

    result = await action.run(
        account_id=account_id,
        payload=Set2FAPayload(
            mode="set_or_change",
            password_enc_b64="not-base64!!!",
        ),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.ok is False
    assert result.detail["reason"] == "invalid_password_enc"
    assert client.calls == []
