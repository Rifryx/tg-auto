"""Юнит-тесты реестра слушателей и динамики campaign_lifecycle (аудит #4/#12).

БД/Redis не нужны: ``CampaignRepository`` и ``round_robin_account`` подменяются
фейками, ClientPool/клиент — моки. Проверяем поштучные attach/detach, load_all,
идемпотентность и диспетчеризацию событий жизненного цикла.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from modules.commenting.worker import registry as reg

pytestmark = pytest.mark.asyncio


# --- фейки -------------------------------------------------------------------


class _FakeClient:
    def __init__(self, entity_id=999):
        self._entity_id = entity_id
        self.added = []
        self.removed = []

    async def get_entity(self, target):
        return SimpleNamespace(id=self._entity_id)

    def add_event_handler(self, handler, event):
        self.added.append((handler, event))

    def remove_event_handler(self, handler, event):
        self.removed.append((handler, event))


class _FakePool:
    def __init__(self, client):
        self._client = client
        self.gets = []
        self.releases = []

    async def get(self, account_id):
        self.gets.append(account_id)
        return self._client

    async def release(self, account_id):
        self.releases.append(account_id)


class _SpyTaskQueue:
    def __init__(self):
        self.enqueued = []

    async def enqueue(self, name, *args, **kwargs):
        self.enqueued.append((name, args))
        return "job"


class _NullCtx:
    def __enter__(self):
        return object()  # сессия не используется (репозиторий замокан)

    def __exit__(self, *exc):
        return False


def _ctx(client):
    return {
        "session_factory": lambda: _NullCtx(),
        "client_pool": _FakePool(client),
        "task_queue": _SpyTaskQueue(),
    }


def _campaign(cid, *, enabled=True):
    return SimpleNamespace(
        id=cid, enabled=enabled, target_channel=f"@ch{cid}", discussion_group_id=500 + cid
    )


def _patch_repo(monkeypatch, campaigns: dict, *, account_for=None):
    """Подменяет CampaignRepository и round_robin_account в модуле registry."""

    class _FakeCampaignRepo:
        def __init__(self, session):
            pass

        def get(self, cid):
            return campaigns.get(cid)

        def list_all(self):
            return list(campaigns.values())

    async def _fake_rr(session, campaign_id, cursor):
        if account_for is None:
            return SimpleNamespace(id=10 + campaign_id)
        return account_for(campaign_id)

    monkeypatch.setattr(reg, "CampaignRepository", _FakeCampaignRepo)
    monkeypatch.setattr(reg, "round_robin_account", _fake_rr)


# --- 1. load_all подключает все enabled-кампании -----------------------------


async def test_load_all_attaches_all_enabled(monkeypatch):
    campaigns = {1: _campaign(1), 2: _campaign(2), 3: _campaign(3, enabled=False)}
    _patch_repo(monkeypatch, campaigns)
    client = _FakeClient()
    ctx = _ctx(client)

    registry = reg.ListenerRegistry()
    started = await registry.load_all(ctx)

    assert started == [1, 2]                 # disabled #3 пропущена
    assert registry.active() == [1, 2]
    assert len(client.added) == 2            # по одному NewMessage-handler на кампанию


# --- 2. attach идемпотентен (повторное событие безопасно) --------------------


async def test_attach_idempotent(monkeypatch):
    _patch_repo(monkeypatch, {1: _campaign(1)})
    client = _FakeClient()
    ctx = _ctx(client)
    registry = reg.ListenerRegistry()

    assert await registry.attach(1, ctx) is True
    assert await registry.attach(1, ctx) is True   # повтор — no-op
    assert len(client.added) == 1                   # handler добавлен ровно один раз


# --- 3. detach снимает handler ДО исчезновения кампании ----------------------


async def test_detach_removes_handler_and_releases(monkeypatch):
    _patch_repo(monkeypatch, {1: _campaign(1)})
    client = _FakeClient()
    ctx = _ctx(client)
    registry = reg.ListenerRegistry()
    await registry.attach(1, ctx)

    assert await registry.detach(1) is True
    assert registry.active() == []
    assert len(client.removed) == 1
    assert ctx["client_pool"].releases == [11]      # аккаунт отпущен
    # повторный detach безопасен
    assert await registry.detach(1) is False


# --- 4. attach без assigned-аккаунтов не подключает; появился аккаунт → attach -


async def test_attach_without_account_then_with(monkeypatch):
    state = {"has_account": False}

    def account_for(campaign_id):
        return SimpleNamespace(id=77) if state["has_account"] else None

    _patch_repo(monkeypatch, {1: _campaign(1)}, account_for=account_for)
    client = _FakeClient()
    ctx = _ctx(client)
    registry = reg.ListenerRegistry()

    # нет аккаунтов — слушатель не подключается
    assert await registry.attach(1, ctx) is False
    assert registry.active() == []

    # привязали первый аккаунт → повторный attach подключает
    state["has_account"] = True
    assert await registry.attach(1, ctx) is True
    assert registry.active() == [1]


# --- 5. lifecycle-листенер: событие → attach/detach через реестр -------------


class _SpyRegistry:
    def __init__(self):
        self.calls = []

    async def attach(self, campaign_id, ctx):
        self.calls.append(("attach", campaign_id))
        return True

    async def detach(self, campaign_id):
        self.calls.append(("detach", campaign_id))
        return True


async def test_lifecycle_handle_dispatches_attach_detach():
    spy = _SpyRegistry()
    listener = reg.CampaignLifecycleListener(spy, ctx={}, redis_url="redis://x")

    await listener._handle(json.dumps({"campaign_id": 5, "action": "attach"}))
    await listener._handle(json.dumps({"campaign_id": 5, "action": "detach"}).encode())
    # мусор игнорируется, цикл не падает
    await listener._handle(b"not-json")
    await listener._handle(json.dumps({"campaign_id": 5, "action": "weird"}))
    await listener._handle(json.dumps({"action": "attach"}))  # нет campaign_id

    assert spy.calls == [("attach", 5), ("detach", 5)]


async def test_lifecycle_handle_survives_registry_error():
    class _Boom:
        async def attach(self, campaign_id, ctx):
            raise RuntimeError("boom")

        async def detach(self, campaign_id):
            raise RuntimeError("boom")

    listener = reg.CampaignLifecycleListener(_Boom(), ctx={}, redis_url="redis://x")
    # исключение внутри обработки не пробрасывается наружу (цикл выживает)
    await listener._handle(json.dumps({"campaign_id": 1, "action": "attach"}))
