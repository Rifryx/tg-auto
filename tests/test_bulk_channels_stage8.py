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


async def test_create_channel_public_sets_username(session):
    _clean(session)
    account = _make_account(session)

    class _Client:
        def __init__(self):
            self.requests: list[str] = []

        async def __call__(self, request):
            self.requests.append(type(request).__name__)
            # CreateChannel → Updates с новым каналом; UpdateUsername → ок.
            return SimpleNamespace(
                chats=[SimpleNamespace(id=2002, access_hash=888, username=None)],
                updates=[],
            )

    client = _Client()
    action = ACTION_REGISTRY[BulkActionType.CREATE_CHANNEL.value]
    payload = CreateChannelPayload(title="Pub", is_public=True, public_username="mychan5")
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=client,
    )

    assert result.ok is True
    assert "UpdateUsernameRequest" in client.requests
    assert result.detail["username"] == "mychan5"
    session.expire_all()
    assert session.query(ProjectChannel).one().username == "mychan5"


def test_create_channel_rejects_bad_username():
    import pytest as _pytest

    with _pytest.raises(Exception):
        CreateChannelPayload(title="x", is_public=True, public_username="ab")  # слишком коротко


async def test_create_channel_private_exports_invite_link(session):
    """Приватный канал → ExportChatInvite, ссылка сохраняется; реакции по умолч. вкл."""
    _clean(session)
    account = _make_account(session)

    class _Client:
        def __init__(self):
            self.requests: list[str] = []

        async def __call__(self, request):
            name = type(request).__name__
            self.requests.append(name)
            if name == "ExportChatInviteRequest":
                return SimpleNamespace(link="https://t.me/+abc123")
            return SimpleNamespace(
                chats=[SimpleNamespace(id=3003, access_hash=999, username=None)],
                updates=[],
            )

    client = _Client()
    action = ACTION_REGISTRY[BulkActionType.CREATE_CHANNEL.value]
    payload = CreateChannelPayload(title="Priv")  # is_public=False по умолчанию
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=client,
    )

    assert result.ok is True
    assert "ExportChatInviteRequest" in client.requests
    assert "SetChatAvailableReactionsRequest" in client.requests
    assert result.detail["invite_link"] == "https://t.me/+abc123"
    session.expire_all()
    assert session.query(ProjectChannel).one().invite_link == "https://t.me/+abc123"


async def test_create_channel_public_exports_invite_link(session):
    """Публичный канал → инвайт-ссылка ВСЁ РАВНО экспортируется и сохраняется.

    Нужна на случай, когда запрошенный @username занят/невалиден: тогда канал
    остаётся без t.me/<username>, и инвайт-ссылка — единственный способ попасть
    в него. UI обязан иметь ссылку на любой созданный канал/чат.
    """
    _clean(session)
    account = _make_account(session)

    class _Client:
        def __init__(self):
            self.requests: list[str] = []

        async def __call__(self, request):
            name = type(request).__name__
            self.requests.append(name)
            if name == "ExportChatInviteRequest":
                return SimpleNamespace(link="https://t.me/+pubInvite")
            return SimpleNamespace(
                chats=[SimpleNamespace(id=4004, access_hash=1, username=None)],
                updates=[],
            )

    client = _Client()
    action = ACTION_REGISTRY[BulkActionType.CREATE_CHANNEL.value]
    payload = CreateChannelPayload(title="Pub", is_public=True, public_username="pubchan5")
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=client,
    )

    assert result.ok is True
    assert "ExportChatInviteRequest" in client.requests
    assert result.detail["invite_link"] == "https://t.me/+pubInvite"


# ── первый пост: эффекты, медиа, тумблер закрепления ─────────────────────────


class _PostClient:
    """Мок клиента с методами для отправки первого поста."""

    def __init__(self, channel_id=6006):
        self.channel_id = channel_id
        self.requests: list[str] = []
        self.sent_message = None  # (text, entities)
        self.sent_file = None  # (caption, entities, file)
        self.uploaded = None

    async def __call__(self, request):
        self.requests.append(type(request).__name__)
        return SimpleNamespace(
            chats=[SimpleNamespace(id=self.channel_id, access_hash=5, username=None)],
            updates=[],
        )

    async def get_entity(self, _x):
        return SimpleNamespace(id=self.channel_id)

    async def upload_file(self, data, file_name=None):
        self.uploaded = (data, file_name)
        return "UPLOADED"

    async def send_message(self, _entity, text, formatting_entities=None):
        self.sent_message = (text, formatting_entities)
        return SimpleNamespace(id=555)

    async def send_file(self, _entity, file=None, caption="", formatting_entities=None, **_kw):
        self.sent_file = (caption, formatting_entities, file)
        return SimpleNamespace(id=556)


async def test_create_channel_first_post_text_entities_and_pin(session):
    """Текст с эффектами → send_message с entities; закрепляется по умолчанию."""
    _clean(session)
    account = _make_account(session)
    client = _PostClient()

    action = ACTION_REGISTRY[BulkActionType.CREATE_CHANNEL.value]
    payload = CreateChannelPayload(title="C", first_post="привет **мир** и ||секрет||")
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=client,
    )

    assert result.ok is True
    text_sent, entities = client.sent_message
    assert text_sent == "привет мир и секрет"
    kinds = {type(e).__name__ for e in entities}
    assert "MessageEntityBold" in kinds
    assert "MessageEntitySpoiler" in kinds
    # Закрепление по умолчанию включено.
    assert "UpdatePinnedMessageRequest" in client.requests
    assert result.detail["pinned_message_id"] == 555
    session.expire_all()
    assert session.query(ProjectChannel).one().pinned_message_id == 555


async def test_create_channel_first_post_no_pin(session):
    """first_post_pin=False → пост отправлен, но не закреплён."""
    _clean(session)
    account = _make_account(session)
    client = _PostClient(channel_id=6007)

    action = ACTION_REGISTRY[BulkActionType.CREATE_CHANNEL.value]
    payload = CreateChannelPayload(title="C", first_post="текст", first_post_pin=False)
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=client,
    )

    assert result.ok is True
    assert client.sent_message is not None
    assert "UpdatePinnedMessageRequest" not in client.requests
    assert result.detail["pinned_message_id"] is None


async def test_create_channel_first_post_plain_no_markdown(session):
    """first_post_markdown=False → маркеры остаются как есть, entities нет."""
    _clean(session)
    account = _make_account(session)
    client = _PostClient(channel_id=6008)

    action = ACTION_REGISTRY[BulkActionType.CREATE_CHANNEL.value]
    payload = CreateChannelPayload(
        title="C", first_post="**как есть**", first_post_markdown=False
    )
    await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=client,
    )

    text_sent, entities = client.sent_message
    assert text_sent == "**как есть**"
    assert entities is None


async def test_create_channel_first_post_media(session):
    """Медиа-пост → upload_file + send_file с подписью."""
    _clean(session)
    account = _make_account(session)

    from core.models import MediaAsset

    asset = MediaAsset(
        user_id="u1", mime="image/png", bytes=b"PNGDATA",
        size_bytes=7, sha256="a" * 64, filename="pic.png",
    )
    session.add(asset)
    session.commit()
    asset_id = asset.id

    client = _PostClient(channel_id=6009)
    action = ACTION_REGISTRY[BulkActionType.CREATE_CHANNEL.value]
    payload = CreateChannelPayload(
        title="C", first_post="подпись", first_post_media_id=asset_id
    )
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=client,
    )

    assert result.ok is True
    assert client.uploaded == (b"PNGDATA", "pic.png")
    caption, _ent, file = client.sent_file
    assert caption == "подпись"
    assert file == "UPLOADED"
    assert client.sent_message is None  # медиа → send_file, не send_message

    session.execute(text("TRUNCATE media_assets RESTART IDENTITY CASCADE"))
    session.commit()


async def test_create_channel_sets_photo(session):
    """photo_media_id → upload_file + EditPhotoRequest; detail.photo_set=True."""
    _clean(session)
    account = _make_account(session)

    from core.models import MediaAsset

    asset = MediaAsset(
        user_id="u1", mime="image/png", bytes=b"AVATAR", size_bytes=6,
        sha256="b" * 64, filename="ava.png",
    )
    session.add(asset)
    session.commit()
    asset_id = asset.id

    client = _PostClient(channel_id=6010)
    action = ACTION_REGISTRY[BulkActionType.CREATE_CHANNEL.value]
    payload = CreateChannelPayload(title="C", photo_media_id=asset_id)
    result = await action.run(
        account_id=account.id,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=client,
    )

    assert result.ok is True
    assert client.uploaded == (b"AVATAR", "ava.png")
    assert "EditPhotoRequest" in client.requests
    assert result.detail["photo_set"] is True

    session.execute(text("TRUNCATE media_assets RESTART IDENTITY CASCADE"))
    session.commit()


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
