"""Интеграционные тесты bulk-actions для каналов (этап 8 УТП).

Fake-клиент ловит Telethon-request'ы и возвращает поддельные entity/messages,
чтобы можно было проверить путь без реальной сети. Постгрес нужен для
health-инцидентов (вызовы идут через around_telethon_call).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from core.models import Account
from modules.bulk.actions.join_channels import JoinChannelsPayload, _run as join_run
from modules.bulk.actions.leave_channels import (
    LeaveChannelsPayload,
    _run as leave_run,
)
from modules.bulk.actions.view_channel_posts import (
    ViewChannelPostsPayload,
    _run as view_run,
)

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
_PHONE = iter(range(30_000_000_000, 30_001_000_000))


class _FakeEntity:
    def __init__(self, ident: str, entity_id: int = 111) -> None:
        self.ident = ident
        self.id = entity_id


class _FakeMessage:
    def __init__(self, mid: int) -> None:
        self.id = mid


class _FakeClient:
    """Ловит все Telethon-вызовы. Настраивается по типу запроса."""

    def __init__(
        self,
        *,
        entities: dict[str, _FakeEntity] | None = None,
        occupied: set[str] | None = None,
    ) -> None:
        self.entities = entities or {}
        self.occupied = occupied or set()
        self.calls: list[str] = []

    async def get_entity(self, ref):
        self.calls.append(f"get_entity:{ref}")
        entity = self.entities.get(ref)
        if entity is None:
            raise RuntimeError(f"unknown entity {ref!r}")
        return entity

    async def get_messages(self, entity, *, limit):
        self.calls.append(f"get_messages:{getattr(entity,'ident',None)}:{limit}")
        return [_FakeMessage(mid=42), _FakeMessage(mid=41)]

    async def send_read_acknowledge(self, entity, *, max_id):
        self.calls.append(f"read_ack:{getattr(entity,'ident',None)}:{max_id}")
        return True

    async def __call__(self, request):
        # JoinChannel/Leave — параметр entity; Import — invite hash.
        name = type(request).__name__
        if isinstance(request, JoinChannelRequest):
            self.calls.append(f"join:{getattr(request.channel,'ident',None)}")
        elif isinstance(request, LeaveChannelRequest):
            self.calls.append(f"leave:{getattr(request.channel,'ident',None)}")
        elif isinstance(request, ImportChatInviteRequest):
            self.calls.append(f"invite:{request.hash}")
            if request.hash in self.occupied:
                raise RuntimeError("invite invalid")
        else:
            self.calls.append(f"call:{name}")
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


# ── join_channels: public + invite вместе ─────────────────────────────────────


async def test_join_channels_mixed_refs(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient(
        entities={"news": _FakeEntity("news"), "chat": _FakeEntity("chat")}
    )
    result = await join_run(
        account_id=account_id,
        payload=JoinChannelsPayload(
            channel_refs=["@news", "https://t.me/chat", "https://t.me/+abcXYZ"]
        ),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.ok is True
    assert set(result.detail["joined"]) == {
        "@news", "https://t.me/chat", "https://t.me/+abcXYZ"
    }
    assert result.detail["errors"] == {}
    # Публичные — get_entity + JoinChannel; приват — Import.
    assert any(c.startswith("join:news") for c in client.calls)
    assert any(c.startswith("join:chat") for c in client.calls)
    assert "invite:abcXYZ" in client.calls


async def test_join_channels_isolates_per_ref_errors(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient(
        entities={"good": _FakeEntity("good")}, occupied={"badinvite"}
    )
    result = await join_run(
        account_id=account_id,
        payload=JoinChannelsPayload(
            channel_refs=["@good", "@missing", "t.me/+badinvite"]
        ),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.detail["joined"] == ["@good"]
    assert set(result.detail["errors"].keys()) == {"@missing", "t.me/+badinvite"}


async def test_join_channels_rejects_folders_in_bulk(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient()
    result = await join_run(
        account_id=account_id,
        payload=JoinChannelsPayload(channel_refs=["https://t.me/addlist/xyz"]),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.detail["errors"] == {
        "https://t.me/addlist/xyz": "folders_unsupported_in_bulk"
    }
    # Никаких вызовов Telethon — folders отсекаются до сети.
    assert client.calls == []


# ── leave_channels ────────────────────────────────────────────────────────────


async def test_leave_channels_calls_leave_per_ref(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient(entities={"news": _FakeEntity("news")})
    result = await leave_run(
        account_id=account_id,
        payload=LeaveChannelsPayload(channel_refs=["@news"]),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.detail["left"] == ["@news"]
    assert "leave:news" in client.calls


# ── view_channel_posts ────────────────────────────────────────────────────────


async def test_view_channel_posts_reads_and_marks_read(session):
    _clean(session)
    account_id = _make_account(session)
    client = _FakeClient(entities={"news": _FakeEntity("news")})
    result = await view_run(
        account_id=account_id,
        payload=ViewChannelPostsPayload(channel_refs=["@news"], depth=3),
        session_factory=_factory(session),
        publisher=None,
        client=client,
    )
    assert result.detail["viewed"] == {"@news": 2}  # fake отдаёт 2 сообщения
    assert "get_messages:news:3" in client.calls
    assert "read_ack:news:42" in client.calls
