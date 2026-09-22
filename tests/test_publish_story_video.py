"""Тесты video-Stories в publish_story (этап 9, backlog #2).

Без реального Telegram: фейковый клиент запоминает загрузки и SendStoryRequest,
проверяем что мы построили правильную media (photo vs video-document).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from telethon.tl.functions.stories import SendStoryRequest
from telethon.tl.types import (
    DocumentAttributeVideo,
    InputMediaUploadedDocument,
    InputMediaUploadedPhoto,
)

from core.config import get_settings
from core.models import MediaAsset
from modules.bulk.actions.publish_story import (
    PublishStoryPayload,
    _build_input_media,
    _is_video,
    _run,
)

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


class _FakeClient:
    """Запоминает upload'ы и SendStoryRequest, чтобы мы могли инспектировать
    построенное media."""

    def __init__(self):
        self.uploads: list[dict] = []
        self.last_request = None

    async def upload_file(self, blob, *, file_name=None):
        # Возвращаем «файл-хендл» — просто уникальный маркер.
        self.uploads.append({"size": len(blob), "file_name": file_name})
        return f"input_file_{len(self.uploads)}"

    async def __call__(self, request):
        self.last_request = request
        # SendStoryRequest ожидает Updates — вернём заглушку.
        from types import SimpleNamespace
        return SimpleNamespace(updates=[])


def _clean(session):
    session.execute(text("TRUNCATE media_assets RESTART IDENTITY CASCADE"))
    session.commit()


# ── helpers ────────────────────────────────────────────────────────────────


def test_is_video_by_mime():
    assert _is_video("video/mp4") is True
    assert _is_video("VIDEO/mp4") is True
    assert _is_video("image/jpeg") is False
    assert _is_video(None) is False
    assert _is_video("") is False


def test_build_input_media_photo():
    payload = PublishStoryPayload(media_b64="aGVsbG8=")
    media = _build_input_media(
        "file", mime="image/jpeg", is_video=False, thumb=None, payload=payload
    )
    assert isinstance(media, InputMediaUploadedPhoto)
    assert media.file == "file"


def test_build_input_media_video():
    payload = PublishStoryPayload(
        media_asset_id=1,
        video_duration_sec=15,
        video_width=1080,
        video_height=1920,
    )
    media = _build_input_media(
        "file", mime="video/mp4", is_video=True,
        thumb="thumb_file", payload=payload,
    )
    assert isinstance(media, InputMediaUploadedDocument)
    assert media.file == "file"
    assert media.mime_type == "video/mp4"
    assert media.thumb == "thumb_file"
    assert len(media.attributes) == 1
    attr = media.attributes[0]
    assert isinstance(attr, DocumentAttributeVideo)
    assert attr.duration == 15
    assert attr.w == 1080
    assert attr.h == 1920
    assert attr.supports_streaming is True


def test_build_input_media_video_defaults_mime_to_mp4():
    """Если mime не задан, но is_video=True — mime_type='video/mp4' fallback."""
    payload = PublishStoryPayload(
        media_asset_id=1,
        video_duration_sec=1,
        video_width=100,
        video_height=100,
    )
    media = _build_input_media(
        "f", mime=None, is_video=True, thumb=None, payload=payload
    )
    assert media.mime_type == "video/mp4"


# ── payload validation ────────────────────────────────────────────────────


def test_video_fields_all_or_none():
    """Все три video-атрибута — либо все, либо ни один."""
    with pytest.raises(Exception):
        PublishStoryPayload(media_asset_id=1, video_duration_sec=15)
    with pytest.raises(Exception):
        PublishStoryPayload(
            media_asset_id=1, video_duration_sec=15, video_width=1080
        )
    # Все три — ОК:
    p = PublishStoryPayload(
        media_asset_id=1,
        video_duration_sec=15, video_width=1080, video_height=1920,
    )
    assert p.video_duration_sec == 15


def test_thumb_requires_media_asset_id():
    """thumb_asset_id + media_b64 = 422 (нам неоткуда взять bytes)."""
    with pytest.raises(Exception):
        PublishStoryPayload(media_b64="aGVsbG8=", thumb_asset_id=1)


def test_thumb_with_media_asset_id_ok():
    p = PublishStoryPayload(media_asset_id=1, thumb_asset_id=2)
    assert p.thumb_asset_id == 2


def test_video_duration_bounds():
    """Stories: макс 60 сек."""
    with pytest.raises(Exception):
        PublishStoryPayload(
            media_asset_id=1,
            video_duration_sec=61, video_width=100, video_height=100,
        )
    with pytest.raises(Exception):
        PublishStoryPayload(
            media_asset_id=1,
            video_duration_sec=0, video_width=100, video_height=100,
        )


# ── _run: end-to-end (mocked Telethon) ────────────────────────────────────


async def test_photo_asset_uses_photo_media(session):
    _clean(session)
    asset = MediaAsset(
        user_id="u1", mime="image/jpeg", bytes=b"jpeg-bytes",
        size_bytes=10, sha256="a" * 64, filename="pic.jpg",
    )
    session.add(asset)
    session.commit()

    client = _FakeClient()
    result = await _run(
        account_id=1,
        payload=PublishStoryPayload(media_asset_id=asset.id, caption="hi"),
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=client,
    )
    assert result.ok
    assert result.detail["media_kind"] == "photo"
    # SendStoryRequest содержит InputMediaUploadedPhoto:
    assert isinstance(client.last_request, SendStoryRequest)
    assert isinstance(client.last_request.media, InputMediaUploadedPhoto)


async def test_video_asset_uses_document_media_with_attributes(session):
    _clean(session)
    asset = MediaAsset(
        user_id="u1", mime="video/mp4", bytes=b"mp4bytes" * 10,
        size_bytes=80, sha256="b" * 64, filename="clip.mp4",
    )
    session.add(asset)
    session.commit()

    client = _FakeClient()
    payload = PublishStoryPayload(
        media_asset_id=asset.id,
        video_duration_sec=10, video_width=720, video_height=1280,
    )
    result = await _run(
        account_id=1, payload=payload,
        session_factory=lambda: _Ctx(session), publisher=None, client=client,
    )
    assert result.ok
    assert result.detail["media_kind"] == "video"
    media = client.last_request.media
    assert isinstance(media, InputMediaUploadedDocument)
    assert media.mime_type == "video/mp4"
    attr = media.attributes[0]
    assert attr.duration == 10
    assert attr.w == 720
    assert attr.h == 1280
    # Thumb не запрашивали → нет второго upload'а:
    assert len(client.uploads) == 1


async def test_video_asset_without_attributes_reports_error(session):
    """MIME video/* но video-поля не заданы → skipped с reason."""
    _clean(session)
    asset = MediaAsset(
        user_id="u1", mime="video/mp4", bytes=b"mp4",
        size_bytes=3, sha256="c" * 64, filename="v.mp4",
    )
    session.add(asset)
    session.commit()

    client = _FakeClient()
    result = await _run(
        account_id=1,
        payload=PublishStoryPayload(media_asset_id=asset.id),
        session_factory=lambda: _Ctx(session), publisher=None, client=client,
    )
    assert result.ok is False
    assert result.detail["reason"] == "video_attributes_required"
    assert result.detail["mime"] == "video/mp4"
    # Telegram не тронут:
    assert client.last_request is None


async def test_video_with_thumb_uploads_both(session):
    _clean(session)
    video = MediaAsset(
        user_id="u1", mime="video/mp4", bytes=b"mp4",
        size_bytes=3, sha256="d" * 64, filename="v.mp4",
    )
    thumb = MediaAsset(
        user_id="u1", mime="image/jpeg", bytes=b"jpg",
        size_bytes=3, sha256="e" * 64, filename="t.jpg",
    )
    session.add_all([video, thumb])
    session.commit()

    client = _FakeClient()
    payload = PublishStoryPayload(
        media_asset_id=video.id, thumb_asset_id=thumb.id,
        video_duration_sec=5, video_width=720, video_height=1280,
    )
    result = await _run(
        account_id=1, payload=payload,
        session_factory=lambda: _Ctx(session), publisher=None, client=client,
    )
    assert result.ok
    # Два upload'а: медиа + thumb:
    assert len(client.uploads) == 2
    # Первое — video (по filename), второе — thumb (без имени в вызове).
    assert client.uploads[0]["file_name"] == "v.mp4"
    media = client.last_request.media
    assert isinstance(media, InputMediaUploadedDocument)
    assert media.thumb is not None


async def test_video_with_missing_thumb_reports_thumb_not_found(session):
    _clean(session)
    video = MediaAsset(
        user_id="u1", mime="video/mp4", bytes=b"mp4",
        size_bytes=3, sha256="f" * 64, filename="v.mp4",
    )
    session.add(video)
    session.commit()

    client = _FakeClient()
    payload = PublishStoryPayload(
        media_asset_id=video.id, thumb_asset_id=999999,
        video_duration_sec=5, video_width=720, video_height=1280,
    )
    result = await _run(
        account_id=1, payload=payload,
        session_factory=lambda: _Ctx(session), publisher=None, client=client,
    )
    assert result.ok is False
    assert result.detail["reason"] == "thumb_asset_not_found"
    # Никаких upload'ов не было:
    assert client.uploads == []


async def test_inline_media_b64_treated_as_photo(session):
    """Legacy inline: без MIME — trip как photo."""
    _clean(session)

    client = _FakeClient()
    result = await _run(
        account_id=1,
        payload=PublishStoryPayload(media_b64="aGVsbG8="),
        session_factory=lambda: _Ctx(session), publisher=None, client=client,
    )
    assert result.ok
    assert result.detail["media_kind"] == "photo"
    assert isinstance(client.last_request.media, InputMediaUploadedPhoto)
