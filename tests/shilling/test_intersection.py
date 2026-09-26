"""Тесты поиска целей «по пересечению каналов».

БД настоящая (CI/postgres); Telethon — фейки (подписки/полный канал).
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest

from core.models import Account
from modules.shilling.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
)
from modules.shilling.schemas import CampaignCreate, TargetCreate
from modules.shilling.worker.intersection import (
    discover_intersection,
    intersection_channel,
)

pytestmark = pytest.mark.asyncio

_PHONE = itertools.count(91_200_000_000)


class _FakePublisher:
    def __init__(self):
        self.events = []

    def publish(self, channel, payload):
        self.events.append((channel, payload))


class _FakePool:
    """Возвращает per-account клиента (у каждого свои подписки)."""

    def __init__(self, clients: dict[int, object]):
        self._clients = clients
        self.released: list[int] = []

    async def get(self, account_id):
        return self._clients[account_id]

    async def release(self, account_id):
        self.released.append(account_id)


def _ent(cid, username, title, *, broadcast=True, left=False):
    return SimpleNamespace(
        id=cid, username=username, title=title, broadcast=broadcast, left=left
    )


class _AccountClient:
    """channels: список (id, username, title); comments: username -> linked_chat_id|None."""

    def __init__(self, channels, comments):
        self._channels = channels
        self._comments = comments

    async def get_dialogs(self, limit=None):
        return [SimpleNamespace(entity=_ent(c, u, t)) for (c, u, t) in self._channels]

    async def get_entity(self, ref):
        for (c, u, t) in self._channels:
            if u == ref:
                return _ent(c, u, t)
        return _ent(-1, ref, ref)

    async def __call__(self, request):
        if "GetFullChannel" in type(request).__name__:
            ent = getattr(request, "channel", None)
            username = getattr(ent, "username", None)
            linked = self._comments.get(username, -200)  # по умолчанию комменты есть
            return SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=linked))
        return None


class _Rng:
    def uniform(self, a, b):
        return a


def _factory(session):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *exc):
            return False

    return lambda: _Ctx()


def _acc(session, status="assigned") -> int:
    acc = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status=status,
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(acc)
    session.flush()
    return acc.id


async def _noop_sleep(_):
    return None


def _ctx(session, clients, publisher):
    return {
        "session_factory": _factory(session),
        "now": None,
        "rng": _Rng(),
        "sleep": _noop_sleep,
        "client_pool": _FakePool(clients),
        "publisher": publisher,
    }


def _campaign_with_accounts(session, n=3):
    campaign = CampaignRepository(session).create(
        CampaignCreate(name="c", brand_name="B")
    )
    session.flush()
    link_repo = CampaignAccountRepository(session)
    ids = []
    for _ in range(n):
        aid = _acc(session)
        link_repo.attach(campaign.id, aid, role_id=None, is_reserve=False)
        ids.append(aid)
    session.commit()
    return campaign.id, ids


async def test_intersection_threshold_and_comments(session):
    cid, ids = _campaign_with_accounts(session, 3)
    a, b, c = ids
    # chan1: у всех троих, есть комменты → пройдёт
    # chan2: у A и B, комментов НЕТ → отсеется фазой 2
    # chan3: только у C → ниже порога
    comments = {"chan1": -111, "chan2": None, "chan3": -333}
    clients = {
        a: _AccountClient([(101, "chan1", "Channel 1"), (102, "chan2", "Channel 2")], comments),
        b: _AccountClient([(101, "chan1", "Channel 1"), (102, "chan2", "Channel 2")], comments),
        c: _AccountClient([(101, "chan1", "Channel 1"), (103, "chan3", "Channel 3")], comments),
    }
    pub = _FakePublisher()
    report = await discover_intersection(_ctx(session, clients, pub), cid, "job1", min_accounts=2)

    assert report.ok is True
    assert report.accounts_total == 3 and report.accounts_scanned == 3
    found = {ch.username: ch for ch in report.channels}
    assert set(found) == {"chan1"}
    assert found["chan1"].subscriber_count == 3
    assert found["chan1"].raw_input == "chan1"
    assert found["chan1"].already_target is False
    # все клиенты освобождены (3 в фазе 1 + probe в фазе 2)
    assert pub.events[-1][1]["event"] == "done"
    channels = {c for c, _ in pub.events}
    assert channels == {intersection_channel("job1")}


async def test_intersection_marks_existing_targets(session):
    cid, ids = _campaign_with_accounts(session, 2)
    a, b = ids
    comments = {"chan1": -111}
    clients = {
        a: _AccountClient([(101, "chan1", "Channel 1")], comments),
        b: _AccountClient([(101, "chan1", "Channel 1")], comments),
    }
    # заранее добавляем chan1 в цели
    CampaignTargetRepository(session).create(cid, TargetCreate(raw_input="chan1", kind="username"))
    session.commit()

    pub = _FakePublisher()
    report = await discover_intersection(_ctx(session, clients, pub), cid, "job2", min_accounts=2)
    assert report.ok is True
    found = {ch.username: ch for ch in report.channels}
    assert found["chan1"].already_target is True


async def test_intersection_no_accounts_fails(session):
    campaign = CampaignRepository(session).create(CampaignCreate(name="empty", brand_name="B"))
    session.commit()
    pub = _FakePublisher()
    report = await discover_intersection(_ctx(session, {}, pub), campaign.id, "job3", min_accounts=2)
    assert report.ok is False
    assert "no usable accounts" in (report.reason or "")
    assert pub.events and pub.events[-1][1]["event"] == "done"


async def test_intersection_higher_threshold_excludes(session):
    cid, ids = _campaign_with_accounts(session, 3)
    a, b, c = ids
    comments = {"chan1": -111, "chan2": -222}
    clients = {
        a: _AccountClient([(101, "chan1", "C1"), (102, "chan2", "C2")], comments),
        b: _AccountClient([(101, "chan1", "C1")], comments),
        c: _AccountClient([(101, "chan1", "C1")], comments),
    }
    pub = _FakePublisher()
    # порог 3 → только chan1 (у всех троих); chan2 только у A
    report = await discover_intersection(_ctx(session, clients, pub), cid, "job4", min_accounts=3)
    found = {ch.username for ch in report.channels}
    assert found == {"chan1"}
