"""manage_channel_post: смена аватара (set_photo), удаление канала
(delete_channel) + prune созданных каналов под реальность."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from core.config import get_settings
from core.enums import BulkActionType
from core.models import Account, MediaAsset, ProjectChannel
from core.repositories.project_channel import ProjectChannelRepository
from modules.bulk.actions import ACTION_REGISTRY
from modules.bulk.actions.manage_channel_post import ManageChannelPostPayload

pytestmark = pytest.mark.asyncio

_TABLES = ("project_channels", "accounts", "media_assets")


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


def _make_account(session):
    a = Account(
        phone="+79990000009", session_enc=b"e", status="pool",
        device_model="d", system_version="v", app_version="a",
        lang_code="uk", system_lang_code="uk-UA",
    )
    session.add(a)
    session.commit()
    return a


class _Client:
    def __init__(self):
        self.requests: list[str] = []
        self.uploaded = None

    async def get_entity(self, _peer):
        return SimpleNamespace(id=777)

    async def upload_file(self, data, file_name=None):
        self.uploaded = (data, file_name)
        return "UPLOADED"

    async def __call__(self, req):
        self.requests.append(type(req).__name__)
        return None


async def test_set_photo_uploads_and_edits(session):
    _clean(session)
    account = _make_account(session)
    asset = MediaAsset(
        user_id="u1", mime="image/png", bytes=b"AVA", size_bytes=3,
        sha256="c" * 64, filename="a.png",
    )
    session.add(asset)
    session.commit()

    client = _Client()
    action = ACTION_REGISTRY[BulkActionType.MANAGE_CHANNEL_POST.value]
    payload = ManageChannelPostPayload(
        channel_tg_id=777, channel_access_hash=5, mode="set_photo",
        photo_media_id=asset.id,
    )
    result = await action.run(
        account_id=account.id, payload=payload,
        session_factory=lambda: _Ctx(session), publisher=None, client=client,
    )
    assert result.ok is True
    assert client.uploaded == (b"AVA", "a.png")
    assert "EditPhotoRequest" in client.requests
    assert result.detail["photo_set"] is True
    session.execute(text("TRUNCATE media_assets RESTART IDENTITY CASCADE"))
    session.commit()


async def test_delete_channel_removes_row(session):
    _clean(session)
    account = _make_account(session)
    repo = ProjectChannelRepository(session)
    repo.create(
        account_id=account.id, project_id=None, channel_tg_id=777,
        channel_access_hash=5, title="C", username=None, is_megagroup=False,
    )
    session.commit()

    client = _Client()
    action = ACTION_REGISTRY[BulkActionType.MANAGE_CHANNEL_POST.value]
    payload = ManageChannelPostPayload(
        channel_tg_id=777, channel_access_hash=5, mode="delete_channel"
    )
    result = await action.run(
        account_id=account.id, payload=payload,
        session_factory=lambda: _Ctx(session), publisher=None, client=client,
    )
    assert result.ok is True
    assert "DeleteChannelRequest" in client.requests
    assert result.detail["channel_deleted"] is True
    session.expire_all()
    assert session.query(ProjectChannel).count() == 0


def test_set_photo_requires_media_id():
    with pytest.raises(Exception):
        ManageChannelPostPayload(channel_tg_id=1, mode="set_photo")


async def test_pin_dialog_sets_is_pinned(session):
    """pin_dialog → ToggleDialogPinRequest + project_channels.is_pinned=True."""
    _clean(session)
    account = _make_account(session)
    repo = ProjectChannelRepository(session)
    repo.create(
        account_id=account.id, project_id=None, channel_tg_id=777,
        channel_access_hash=5, title="C", username=None, is_megagroup=False,
    )
    session.commit()

    class _PinClient(_Client):
        async def get_input_entity(self, _e):
            return SimpleNamespace(channel_id=777, access_hash=5)

    client = _PinClient()
    action = ACTION_REGISTRY[BulkActionType.MANAGE_CHANNEL_POST.value]

    result = await action.run(
        account_id=account.id,
        payload=ManageChannelPostPayload(
            channel_tg_id=777, channel_access_hash=5, mode="pin_dialog"
        ),
        session_factory=lambda: _Ctx(session), publisher=None, client=client,
    )
    assert result.ok is True
    assert "ToggleDialogPinRequest" in client.requests
    assert result.detail["dialog_pinned"] is True
    session.expire_all()
    assert repo.find_by_account_tg(account.id, 777).is_pinned is True

    # unpin → is_pinned=False
    result2 = await action.run(
        account_id=account.id,
        payload=ManageChannelPostPayload(
            channel_tg_id=777, channel_access_hash=5, mode="unpin_dialog"
        ),
        session_factory=lambda: _Ctx(session), publisher=None, client=client,
    )
    assert result2.ok is True
    assert result2.detail["dialog_pinned"] is False
    session.expire_all()
    assert repo.find_by_account_tg(account.id, 777).is_pinned is False


async def test_sync_prunes_only_inaccessible(session):
    """sync_project_channels удаляет лишь каналы с ChannelPrivateError (покинут/
    удалён); доступные и неоднозначные (ошибка сети) — оставляет."""
    from telethon.errors import ChannelPrivateError

    from worker.profiles.dialogs import sync_project_channels_impl

    _clean(session)
    account = _make_account(session)
    repo = ProjectChannelRepository(session)
    for tg in (100, 200, 300):
        repo.create(
            account_id=account.id, project_id=None, channel_tg_id=tg,
            channel_access_hash=tg, title=f"c{tg}", username=None, is_megagroup=False,
        )
    session.commit()

    class _Client:
        async def connect(self):
            return None

        async def get_entity(self, peer):
            cid = int(getattr(peer, "channel_id", 0))
            if cid == 100:
                raise ChannelPrivateError(request=None)  # покинут/удалён → убрать
            if cid == 300:
                raise RuntimeError("network")  # неоднозначно → оставить
            return object()  # 200 доступен

    class _Pool:
        def __init__(self, c):
            self._c = c

        async def get(self, _a):
            return self._c

        async def release(self, _a):
            return None

    ctx = {"session_factory": lambda: _Ctx(session), "client_pool": _Pool(_Client())}
    result = await sync_project_channels_impl(ctx, account.id)

    assert result["removed"] == [100]
    session.expire_all()
    assert sorted(c.channel_tg_id for c in repo.list_for_account(account.id)) == [200, 300]
