"""Тесты media-хранилища и scheduled_at в publish_story (этап 9)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from core.config import get_settings
from core.models import MediaAsset
from core.repositories.media_asset import MediaAssetRepository
from modules.bulk.actions.publish_story import PublishStoryPayload, _run

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


def _clean(session):
    session.execute(text("TRUNCATE media_assets RESTART IDENTITY CASCADE"))
    session.commit()


# ── payload validation ─────────────────────────────────────────────────────


def test_payload_requires_exactly_one_source():
    # Оба источника — 422.
    with pytest.raises(Exception):
        PublishStoryPayload(media_b64="aGVsbG8=", media_asset_id=1)
    # Ни одного — 422.
    with pytest.raises(Exception):
        PublishStoryPayload()


def test_payload_media_asset_id_alone_valid():
    p = PublishStoryPayload(media_asset_id=42)
    assert p.media_asset_id == 42
    assert p.media_b64 is None


def test_payload_media_b64_alone_valid():
    p = PublishStoryPayload(media_b64="aGVsbG8=")
    assert p.media_b64 == "aGVsbG8="
    assert p.media_asset_id is None


# ── media store dedup ─────────────────────────────────────────────────────


def test_get_or_create_dedups_by_sha256(session):
    _clean(session)
    repo = MediaAssetRepository(session)
    a = repo.get_or_create(user_id="u1", blob=b"hello world", mime="image/jpeg")
    b = repo.get_or_create(user_id="u1", blob=b"hello world", mime="image/jpeg")
    session.commit()
    assert a.id == b.id


def test_get_or_create_isolated_between_users(session):
    _clean(session)
    repo = MediaAssetRepository(session)
    a = repo.get_or_create(user_id="u1", blob=b"same", mime="image/jpeg")
    b = repo.get_or_create(user_id="u2", blob=b"same", mime="image/jpeg")
    session.commit()
    assert a.id != b.id
    assert a.sha256 == b.sha256


# ── scheduled_at ──────────────────────────────────────────────────────────


async def test_scheduled_in_future_skips_with_deferred(session):
    """Time-in-future → item уходит в SKIPPED с reason='deferred'."""
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    payload = PublishStoryPayload(
        media_asset_id=99, scheduled_at=future,
    )
    result = await _run(
        account_id=1,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=None,  # не должен вызываться
    )
    assert result.ok is False
    assert result.skipped is True
    assert result.detail["reason"] == "deferred"


async def test_scheduled_in_past_runs_normally(session):
    """Прошедшее scheduled_at → не блокирует выполнение; но у нас нет клиента,
    так что дойдём до media_asset_id lookup и получим not_found (asset нет).
    """
    _clean(session)
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    payload = PublishStoryPayload(
        media_asset_id=99999, scheduled_at=past,
    )
    result = await _run(
        account_id=1,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=None,
    )
    # deferred НЕ сработал → пошли дальше → media_asset_id не найден.
    assert result.detail.get("reason") in {"media_asset_not_found"}


# ── media_asset lookup ────────────────────────────────────────────────────


async def test_media_asset_not_found_returns_error(session):
    _clean(session)
    payload = PublishStoryPayload(media_asset_id=12345)
    result = await _run(
        account_id=1,
        payload=payload,
        session_factory=lambda: _Ctx(session),
        publisher=None,
        client=None,
    )
    assert result.ok is False
    assert result.detail["reason"] == "media_asset_not_found"
