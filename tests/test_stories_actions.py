"""Тесты bulk-actions Stories (этап 9 УТП).

Fake-клиент ловит SendStoryRequest / GetPeerStories / ReadStories и возвращает
поддельные структуры. Постгрес нужен для health-инцидентов внутри
around_telethon_call.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from telethon.tl.functions.stories import (
    GetPeerStoriesRequest,
    ReadStoriesRequest,
    SendStoryRequest,
)
from telethon.tl.types import (
    InputPrivacyValueAllowAll,
    InputPrivacyValueAllowCloseFriends,
)

from core.models import Account
from modules.bulk.actions.publish_story import PublishStoryPayload, _run as publish_run
from modules.bulk.actions.view_stories import ViewStoriesPayload, _run as view_run

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
_PHONE = iter(range(20_000_000_000, 20_001_000_000))


PNG_1x1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAj"
    "CB0C8AAAAASUVORK5CYII="
)


class _FakeEntity:
    def __init__(self, ident: str, entity_id: int = 111) -> None:
        self.ident = ident
        self.id = entity_id


class _FakeStory:
    def __init__(self, sid: int) -> None:
        self.id = sid


class _FakeClient:
    def __init__(
        self,
        *,
        entities: dict[str, _FakeEntity] | None = None,
        stories: list[_FakeStory] | None = None,
    ) -> None:
        self.entities = entities or {}
        self._stories = stories or []
        self.calls: list = []
        self.uploaded_size: int | None = None

    async def upload_file(self, data: bytes):
        self.calls.append(("upload_file", len(data)))
        self.uploaded_size = len(data)
        # Возвращаем произвольный «файл» — Telethon это ожидает.
        return SimpleNamespace(id=42, parts=1)

    async def get_entity(self, ref):
        self.calls.append(("get_entity", ref))
        entity = self.entities.get(ref)
        if entity is None:
            raise RuntimeError(f"unknown {ref!r}")
        return entity

    async def __call__(self, request):
        if isinstance(request, SendStoryRequest):
            self.calls.append(
                (
                    "send_story",
                    {
                        "privacy": type(request.privacy_rules[0]).__name__,
                        "period": request.period,
                        "caption": request.caption,
                    },
                )
            )
            return SimpleNamespace()
        if isinstance(request, GetPeerStoriesRequest):
            self.calls.append(("get_peer_stories", getattr(request.peer, "ident", None)))
            return SimpleNamespace(
                stories=SimpleNamespace(stories=list(self._stories))
            )
        if isinstance(request, ReadStoriesRequest):
            self.calls.append(("read_stories", request.max_id))
            return True
        self.calls.append(("call", type(request).__name__))
        return True


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


def _make_account(session) -> int:
    acc = Account(
        phone=f"+{next(_PHONE)}",
        session_enc=b"enc",
        status="pool",
        device_model="iPhone15,3",
        system_version="17.5.1",
        app_version="10.14.5",
        lang_code="uk",
        system_lang_code="uk-UA",
    )
    session.add(acc)
    session.flush()
    session.commit()
    return acc.id


# ── publish_story ─────────────────────────────────────────────────────────────


async def test_publish_story_uploads_and_sends(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient()

    result = await publish_run(
        account_id=account_id,
        payload=PublishStoryPayload(
            media_b64=PNG_1x1_B64,
            caption="hi",
            privacy="everybody",
            period=86400,
        ),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.ok is True
    assert result.detail["privacy"] == "everybody"
    # Порядок: upload_file → SendStoryRequest
    names = [c[0] for c in client.calls]
    assert names[0] == "upload_file"
    assert names[1] == "send_story"
    send_args = client.calls[1][1]
    assert send_args["period"] == 86400
    assert send_args["caption"] == "hi"
    assert send_args["privacy"] == InputPrivacyValueAllowAll.__name__


async def test_publish_story_close_friends_privacy(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient()
    await publish_run(
        account_id=account_id,
        payload=PublishStoryPayload(
            media_b64=PNG_1x1_B64,
            privacy="close_friends",
        ),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    send = [c for c in client.calls if c[0] == "send_story"][0][1]
    assert send["privacy"] == InputPrivacyValueAllowCloseFriends.__name__


async def test_publish_story_rejects_bad_period(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient()
    result = await publish_run(
        account_id=account_id,
        payload=PublishStoryPayload(media_b64=PNG_1x1_B64, period=999),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.ok is False
    assert result.detail["reason"] == "bad_period"
    # ни upload, ни send не должны были случиться
    assert client.calls == []


async def test_publish_story_invalid_media_b64(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient()
    result = await publish_run(
        account_id=account_id,
        payload=PublishStoryPayload(media_b64="not-base64!!!"),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.ok is False
    assert result.detail["reason"] == "invalid_media_b64"
    assert client.calls == []


# ── view_stories ──────────────────────────────────────────────────────────────


async def test_view_stories_reads_up_to_max_id(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient(
        entities={"blogger": _FakeEntity("blogger")},
        stories=[_FakeStory(sid=5), _FakeStory(sid=10), _FakeStory(sid=7)],
    )
    result = await view_run(
        account_id=account_id,
        payload=ViewStoriesPayload(peer_refs=["@blogger"]),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.detail["viewed"] == {"@blogger": 3}
    assert ("read_stories", 10) in client.calls  # max_id


async def test_view_stories_zero_when_no_stories(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient(entities={"quiet": _FakeEntity("quiet")}, stories=[])
    result = await view_run(
        account_id=account_id,
        payload=ViewStoriesPayload(peer_refs=["@quiet"]),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.detail["viewed"] == {"@quiet": 0}
    # ReadStoriesRequest НЕ должен звучать, если у peer'а stories нет.
    assert not any(c[0] == "read_stories" for c in client.calls)


async def test_view_stories_isolates_per_ref_errors(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient(entities={"ok": _FakeEntity("ok")}, stories=[_FakeStory(1)])
    result = await view_run(
        account_id=account_id,
        payload=ViewStoriesPayload(peer_refs=["@ok", "@missing"]),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.detail["viewed"] == {"@ok": 1}
    assert "@missing" in result.detail["errors"]
