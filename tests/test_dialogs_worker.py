"""Worker-уровень: leave_dialogs_impl детерминированно убирает покинутые
каналы из снапшота, даже если Telegram (get_dialogs) ещё отдаёт их из-за лага.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import worker.profiles.dialogs as dlg
from worker.profiles.dialogs import dialogs_key, leave_dialogs_impl

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, k):
        return self.store.get(k)

    def setex(self, k, _ttl, v):
        self.store[k] = v


class _FakeClient:
    """get_dialogs ВСЕГДА возвращает канал 100 — имитируем лаг Telegram после
    выхода (канал ещё в списке). __call__ просто фиксирует запросы."""

    def __init__(self) -> None:
        self.calls: list[object] = []

    async def connect(self):
        return None

    async def get_dialogs(self):
        chan = SimpleNamespace(
            id=100, access_hash=55, broadcast=True, megagroup=False,
            title="Chan", username=None, participants_count=10, creator=False,
        )
        return [SimpleNamespace(entity=chan, name="Chan", is_group=False)]

    async def __call__(self, req):
        self.calls.append(req)
        return None


class _FakePool:
    def __init__(self, client: _FakeClient) -> None:
        self._c = client

    async def get(self, _account_id):
        return self._c

    async def release(self, _account_id):
        return None


async def test_leave_prunes_left_channel_despite_get_dialogs_lag(monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(dlg, "_redis", lambda: fake_redis)

    account_id = 1
    # Снапшот до выхода: канал 100 присутствует.
    fake_redis.store[dialogs_key(account_id)] = json.dumps(
        {
            "items": [
                {"id": 100, "access_hash": 55, "kind": "channel", "title": "Chan"}
            ],
            "synced_at": "2026-01-01T00:00:00+00:00",
        }
    )

    client = _FakeClient()
    ctx = {"client_pool": _FakePool(client)}

    result = await leave_dialogs_impl(ctx, account_id, dialog_ids=[100])

    assert result == {"left": 1, "requested": 1}
    # Выход реально отправлен.
    assert len(client.calls) == 1
    # Итоговый снапшот НЕ содержит покинутый канал, хотя get_dialogs его вернул.
    final = json.loads(fake_redis.store[dialogs_key(account_id)])
    assert [it["id"] for it in final["items"]] == []


async def test_leave_keeps_other_channels(monkeypatch):
    """Прунится только покинутый id; остальное из свежего снапшота остаётся."""
    fake_redis = _FakeRedis()
    monkeypatch.setattr(dlg, "_redis", lambda: fake_redis)

    account_id = 2
    fake_redis.store[dialogs_key(account_id)] = json.dumps(
        {"items": [{"id": 100, "access_hash": 55, "kind": "channel"}], "synced_at": None}
    )

    class _Client(_FakeClient):
        async def get_dialogs(self):
            # Свежий список: покинутый 100 (лаг) + другой 200.
            a = SimpleNamespace(
                id=100, access_hash=55, broadcast=True, megagroup=False,
                title="Chan", username=None, participants_count=1, creator=False,
            )
            b = SimpleNamespace(
                id=200, access_hash=66, broadcast=True, megagroup=False,
                title="Keep", username=None, participants_count=2, creator=False,
            )
            return [
                SimpleNamespace(entity=a, name="Chan", is_group=False),
                SimpleNamespace(entity=b, name="Keep", is_group=False),
            ]

    client = _Client()
    ctx = {"client_pool": _FakePool(client)}

    await leave_dialogs_impl(ctx, account_id, dialog_ids=[100])

    final = json.loads(fake_redis.store[dialogs_key(account_id)])
    assert [it["id"] for it in final["items"]] == [200]
