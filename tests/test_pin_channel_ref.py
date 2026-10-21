"""pin_channel_ref: закрепление произвольного канала/чата по @username/ссылке."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from core.config import get_settings
from core.enums import BulkActionType
from modules.bulk.actions import ACTION_REGISTRY
from modules.bulk.actions.pin_channel_ref import PinChannelRefPayload

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _Ctx:
    def __init__(self, s):
        self._s = s

    def __enter__(self):
        return self._s

    def __exit__(self, *exc):
        return False


class _Client:
    def __init__(self, username="durov"):
        self.requests: list[str] = []
        self._username = username

    async def get_entity(self, ref):
        return SimpleNamespace(id=1, title="Durov", username=self._username)

    async def get_input_entity(self, _e):
        return SimpleNamespace(channel_id=1, access_hash=2)

    async def __call__(self, req):
        self.requests.append(type(req).__name__)
        return None


async def test_pin_channel_ref_public_returns_link(session):
    client = _Client(username="durov")
    action = ACTION_REGISTRY[BulkActionType.PIN_CHANNEL_REF.value]
    result = await action.run(
        account_id=1,
        payload=PinChannelRefPayload(ref="@durov", pinned=True),
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=client,
    )
    assert result.ok is True
    assert "ToggleDialogPinRequest" in client.requests
    assert result.detail["pinned"] is True
    assert result.detail["link"] == "https://t.me/durov"
    assert result.detail["title"] == "Durov"


async def test_pin_channel_ref_private_no_link(session):
    client = _Client(username=None)
    action = ACTION_REGISTRY[BulkActionType.PIN_CHANNEL_REF.value]
    result = await action.run(
        account_id=1,
        payload=PinChannelRefPayload(ref="https://t.me/+abc", pinned=True),
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=client,
    )
    assert result.ok is True
    assert result.detail["link"] is None


async def test_pin_channel_ref_resolve_failure(session):
    class _Bad(_Client):
        async def get_entity(self, ref):
            raise RuntimeError("not found")

    action = ACTION_REGISTRY[BulkActionType.PIN_CHANNEL_REF.value]
    result = await action.run(
        account_id=1,
        payload=PinChannelRefPayload(ref="@nope", pinned=True),
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=_Bad(),
    )
    assert result.ok is False
    assert result.detail["reason"] == "resolve_failed"
