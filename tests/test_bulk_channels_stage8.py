"""Тесты для этапа 8, backlog: create_channel + expand_folders (join_channels).

Моки Telethon-объектов: реальный клиент не поднимаем.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from core.config import get_settings
from core.enums import BulkActionType
from core.models import Account, Project, ProjectChannel
from core.repositories.project_channel import ProjectChannelRepository
from modules.bulk.actions import ACTION_REGISTRY
from modules.bulk.actions.create_channel import (
    CreateChannelPayload,
    _extract_created_channel,
)
from modules.bulk.actions.join_channels import JoinChannelsPayload

pytestmark = pytest.mark.asyncio

_TABLES = (
    "autopilot_actions",
    "autopilot_goals",
    "project_channels",
    "bulk_job_items",
    "bulk_jobs",
    "accounts",
    "projects",
)


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


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _make_account(session, phone="+79990000001"):
    a = Account(
        phone=phone, session_enc=b"e", status="pool",
        device_model="d", system_version="v", app_version="a",
        lang_code="uk", system_lang_code="uk-UA",
    )
    session.add(a)
    session.flush()
    session.commit()
    return a


# ── create_channel action ───────────────────────────────────────────────────


def test_action_registered_with_correct_governor_key():
    action = ACTION_REGISTRY[BulkActionType.CREATE_CHANNEL.value]
    assert action.requires_client is True
    assert action.governor_key == "bulk_channel"


def test_extract_created_channel_from_updates():
    updates = SimpleNamespace(
        chats=[SimpleNamespace(id=42, access_hash=99, username="mychannel")]
    )
    channel_id, access_hash, username = _extract_created_channel(updates)
    assert channel_id == 42
    assert access_hash == 99
    assert username == "mychannel"


def test_extract_created_channel_raises_on_empty():
    with pytest.raises(RuntimeError):
        _extract_created_channel(SimpleNamespace(chats=[]))


async def test_create_channel_success_writes_project_channels(session):
    _clean(session)
    account = _make_account(session)

    class _Client:
        def __init__(self):
            self._call_num = 0

        async def __call__(self, request):
            # Первый вызов — CreateChannel; возвращаем Updates.
            self._call_num += 1
            return SimpleNamespace(
                chats=[SimpleNamespace(id=1001, access_hash=777, username=None)],
                updates=[],
            )

    action = ACTION_REGISTRY[BulkActionType.CREATE_CHANNEL.value]
    payload = CreateChannelPayload(title="Test", about="hello")
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=_Client(),
    )

    assert result.ok is True
    assert result.detail["channel_tg_id"] == 1001

    session.expire_all()
    rows = session.query(ProjectChannel).all()
    assert len(rows) == 1
    assert rows[0].title == "Test"
    assert rows[0].channel_tg_id == 1001
    assert rows[0].account_id == account.id
    assert rows[0].pinned_message_id is None


async def test_create_channel_dedups_by_account_and_tg_id(session):
    _clean(session)
    account = _make_account(session)

    ProjectChannelRepository(session).create(
        account_id=account.id,
        project_id=None,
        channel_tg_id=5555,
        channel_access_hash=None,
        title="Old",
        username=None,
        is_megagroup=False,
    )
    session.commit()

    class _Client:
        async def __call__(self, _request):
            return SimpleNamespace(
                chats=[SimpleNamespace(id=5555, access_hash=1, username=None)],
                updates=[],
            )

    action = ACTION_REGISTRY[BulkActionType.CREATE_CHANNEL.value]
    payload = CreateChannelPayload(title="New")
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=_Client(),
    )
    assert result.ok is True
    assert result.skipped is True
    assert result.detail["reason"] == "already_created"

    session.expire_all()
    rows = session.query(ProjectChannel).all()
    assert len(rows) == 1
    assert rows[0].title == "Old"  # оригинал не перезаписан


async def test_create_channel_attaches_project(session):
    _clean(session)
    project = Project(user_id="u1", name="P")
    session.add(project)
    session.commit()
    account = _make_account(session)

    class _Client:
        async def __call__(self, _request):
            return SimpleNamespace(
                chats=[SimpleNamespace(id=2001, access_hash=1, username="p_ch")],
                updates=[],
            )

    action = ACTION_REGISTRY[BulkActionType.CREATE_CHANNEL.value]
    payload = CreateChannelPayload(title="Хабр", project_id=project.id)
    await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=_Client(),
    )

    session.expire_all()
    rows = ProjectChannelRepository(session).list_for_project(project.id)
    assert len(rows) == 1
    assert rows[0].username == "p_ch"


# ── join_channels: expand_folders ───────────────────────────────────────────


def test_join_channels_payload_expand_folders_default_true():
    p = JoinChannelsPayload(channel_refs=["https://t.me/durov"])
    assert p.expand_folders is True


def test_join_channels_payload_expand_folders_disabled():
    p = JoinChannelsPayload(
        channel_refs=["https://t.me/addlist/abc"], expand_folders=False
    )
    assert p.expand_folders is False


async def test_join_channels_disabled_expand_returns_error_per_folder(session):
    """expand_folders=False → папка не разворачивается, ошибка per-ref."""
    _clean(session)
    account = _make_account(session)

    class _Client:
        async def __call__(self, _r):
            raise AssertionError("should not touch Telegram when only folder + expand=False")

    action = ACTION_REGISTRY[BulkActionType.JOIN_CHANNELS.value]
    payload = JoinChannelsPayload(
        channel_refs=["https://t.me/addlist/xyz"],
        expand_folders=False,
    )
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=_Client(),
    )
    assert result.detail["errors"]["https://t.me/addlist/xyz"] == "folders_unsupported_in_bulk"


async def test_join_channels_expand_true_calls_join_folder(session, monkeypatch):
    """expand_folders=True → вызывается worker.telegram_folders.join_folder."""
    _clean(session)
    account = _make_account(session)

    from worker import telegram_folders

    async def fake_join_folder(*, client, slug, account_id, session_factory, publisher, **_):  # type: ignore[override]
        assert slug == "xyz"
        return telegram_folders.FolderJoinResult(
            joined_refs=["@a", "@b"], already_in=1
        )

    # Monkeypatch на модуле, где join_folder импортирован.
    import modules.bulk.actions.join_channels as jc_mod

    async def wrapper(client, slug, *, account_id, session_factory, publisher, **kw):
        return telegram_folders.FolderJoinResult(joined_refs=["@a", "@b"], already_in=1)

    monkeypatch.setattr(jc_mod, "join_folder", wrapper)

    action = ACTION_REGISTRY[BulkActionType.JOIN_CHANNELS.value]
    payload = JoinChannelsPayload(
        channel_refs=["https://t.me/addlist/xyz"], expand_folders=True
    )
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=object(),  # клиент не используется — join_folder замокан
    )
    assert result.ok is True
    assert "@a" in result.detail["joined"]
    assert "@b" in result.detail["joined"]
    assert result.detail["folders"]["https://t.me/addlist/xyz"]["already_in"] == 1
