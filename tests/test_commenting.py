"""Тесты серверной части модуля commenting (PROJECT-STAGES §1.2, §10).

БД настоящая; attach/detach идут через state machine. Таблицы чистятся в начале
каждого теста. Авторизация замокана (require_user переопределён).
"""

from __future__ import annotations

import itertools
from datetime import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_publisher, get_task_queue
from core.models import Account
from core.repositories.account import AccountRepository
from core.repositories.account_status_history import AccountStatusHistoryRepository
from modules.commenting.api import router as commenting_router
from modules.commenting.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
)
from modules.commenting.schemas import CampaignCreate
from modules.commenting.worker.registry import (
    ACTION_ATTACH,
    ACTION_DETACH,
    CAMPAIGN_LIFECYCLE_CHANNEL,
)
from sqlalchemy import text

_PHONE = itertools.count(95_000_000_000)
_TABLES = (
    "accounts",
    "account_status_history",
    "warming_activities",
    "health_events",
    '"commenting".campaigns',
    '"commenting".campaign_accounts',
    '"commenting".comment_logs',
)


def _clean(session):
    session.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    session.commit()


def _make_account(session, *, status) -> int:
    acc = Account(
        phone=f"+{next(_PHONE)}",
        session_enc=b"enc",
        status=status,
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


def _make_campaign(session, name="c") -> int:
    campaign = CampaignRepository(session).create(
        CampaignCreate(
            name=name,
            target_channel="@ch",
            base_system_prompt="p",
            llm_provider="deepseek",
            active_hours_start=time(9, 0),
            active_hours_end=time(23, 0),
            active_hours_tz="UTC",
            posting_delay_min_sec=1,
            posting_delay_max_sec=5,
        )
    )
    session.commit()
    return campaign.id


@pytest.fixture
def client(session):
    app = FastAPI()
    app.include_router(commenting_router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_publisher] = lambda: None
    app.dependency_overrides[require_user] = lambda: "tester"
    # Роуты ставят синхронизацию каналов в очередь; настоящий TaskQueue создал
    # бы глобальный пул Redis в event loop TestClient'а и сломал бы соседние тесты.
    app.dependency_overrides[get_task_queue] = lambda: _NullQueue()
    return TestClient(app)


# --- 1. attach из pool → успех -----------------------------------------------


def test_attach_from_pool_succeeds(session, client):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_account(session, status="pool")

    resp = client.post(
        f"/modules/commenting/campaigns/{campaign_id}/accounts",
        json={"account_id": account_id},
    )
    assert resp.status_code == 201, resp.text

    account = AccountRepository(session).get(account_id)
    assert account.status == "assigned"
    assert account.assigned_container_type == "commenting"
    assert account.assigned_container_id == campaign_id
    assert CampaignAccountRepository(session).get(campaign_id, account_id) is not None


# --- 2. attach из cooldown → 409, без изменений ------------------------------


def test_attach_from_cooldown_conflict(session, client):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_account(session, status="cooldown")

    resp = client.post(
        f"/modules/commenting/campaigns/{campaign_id}/accounts",
        json={"account_id": account_id},
    )
    assert resp.status_code == 409

    assert AccountRepository(session).get(account_id).status == "cooldown"
    assert CampaignAccountRepository(session).get(campaign_id, account_id) is None


# --- 3. attach уже привязанного аккаунта → 409 (эксклюзивность) ---------------


def test_attach_already_attached_conflict(session, client):
    _clean(session)
    campaign_a = _make_campaign(session, "A")
    campaign_b = _make_campaign(session, "B")
    account_id = _make_account(session, status="pool")

    ok = client.post(
        f"/modules/commenting/campaigns/{campaign_a}/accounts",
        json={"account_id": account_id},
    )
    assert ok.status_code == 201

    conflict = client.post(
        f"/modules/commenting/campaigns/{campaign_b}/accounts",
        json={"account_id": account_id},
    )
    assert conflict.status_code == 409

    # привязка только к A, аккаунт всё ещё assigned на A
    assert CampaignAccountRepository(session).get(campaign_b, account_id) is None
    account = AccountRepository(session).get(account_id)
    assert account.assigned_container_id == campaign_a


# --- 4. detach → назад в pool, запись удалена, SM вызвана --------------------


def test_detach_returns_to_pool(session, client):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_account(session, status="pool")
    client.post(
        f"/modules/commenting/campaigns/{campaign_id}/accounts",
        json={"account_id": account_id},
    )

    resp = client.delete(
        f"/modules/commenting/campaigns/{campaign_id}/accounts/{account_id}"
    )
    assert resp.status_code == 204

    account = AccountRepository(session).get(account_id)
    assert account.status == "pool"
    assert account.assigned_container_id is None
    assert CampaignAccountRepository(session).get(campaign_id, account_id) is None
    # state machine отметилась в истории (attach + detach)
    reasons = {
        h.reason
        for h in AccountStatusHistoryRepository(session).list_by_account(account_id)
    }
    assert {"container.attach", "container.detach"} <= reasons


# --- 5. attach из banned → 409, без изменений --------------------------------


def test_attach_from_banned_conflict(session, client):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_account(session, status="banned")

    resp = client.post(
        f"/modules/commenting/campaigns/{campaign_id}/accounts",
        json={"account_id": account_id},
    )
    assert resp.status_code == 409

    assert AccountRepository(session).get(account_id).status == "banned"
    assert CampaignAccountRepository(session).get(campaign_id, account_id) is None


# --- Публикация campaign_lifecycle (аудит #4/#12) ----------------------------


class _NullQueue:
    async def enqueue(self, *args, **kwargs):
        return "job"


class _SpyPublisher:
    """Ловит публикации; опционально проверяет инвариант в момент publish."""

    def __init__(self, on_publish=None):
        self.events: list[tuple[str, dict]] = []
        self._on_publish = on_publish

    def publish(self, channel, payload):
        if self._on_publish is not None:
            self._on_publish(channel, payload)
        self.events.append((channel, dict(payload)))

    def lifecycle(self) -> list[dict]:
        return [p for ch, p in self.events if ch == CAMPAIGN_LIFECYCLE_CHANNEL]


def _client_with_publisher(session, publisher) -> TestClient:
    app = FastAPI()
    app.include_router(commenting_router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_publisher] = lambda: publisher
    app.dependency_overrides[require_user] = lambda: "tester"
    # Роуты ставят синхронизацию каналов в очередь; настоящий TaskQueue создал
    # бы глобальный пул Redis в event loop TestClient'а и сломал бы соседние тесты.
    app.dependency_overrides[get_task_queue] = lambda: _NullQueue()
    return TestClient(app)


def test_patch_enabled_publishes_attach_then_detach(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    pub = _SpyPublisher()
    client = _client_with_publisher(session, pub)

    # enabled=true→false → detach
    r1 = client.patch(
        f"/modules/commenting/campaigns/{campaign_id}", json={"enabled": False}
    )
    assert r1.status_code == 200
    # enabled=false→true → attach (динамика без рестарта воркера)
    r2 = client.patch(
        f"/modules/commenting/campaigns/{campaign_id}", json={"enabled": True}
    )
    assert r2.status_code == 200

    assert pub.lifecycle() == [
        {"campaign_id": campaign_id, "action": ACTION_DETACH},
        {"campaign_id": campaign_id, "action": ACTION_ATTACH},
    ]


def test_patch_without_enabled_does_not_publish(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    pub = _SpyPublisher()
    client = _client_with_publisher(session, pub)

    r = client.patch(
        f"/modules/commenting/campaigns/{campaign_id}", json={"name": "renamed"}
    )
    assert r.status_code == 200
    assert pub.lifecycle() == []           # смена не-enabled полей не трогает слушателей


def test_delete_publishes_detach_before_row_removed(session):
    _clean(session)
    campaign_id = _make_campaign(session)

    seen_exists: list[bool] = []

    def on_publish(channel, payload):
        # В момент публикации detach запись кампании ещё должна быть в БД
        # (detach раньше удаления — порядок, не гонка; acceptance #3).
        seen_exists.append(CampaignRepository(session).get(campaign_id) is not None)

    pub = _SpyPublisher(on_publish=on_publish)
    client = _client_with_publisher(session, pub)

    r = client.delete(f"/modules/commenting/campaigns/{campaign_id}")
    assert r.status_code == 204

    assert pub.lifecycle() == [{"campaign_id": campaign_id, "action": ACTION_DETACH}]
    assert seen_exists == [True]                       # detach опубликован ДО удаления
    assert CampaignRepository(session).get(campaign_id) is None  # запись удалена


def test_attach_first_account_publishes_attach(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    account_id = _make_account(session, status="pool")
    pub = _SpyPublisher()
    client = _client_with_publisher(session, pub)

    r = client.post(
        f"/modules/commenting/campaigns/{campaign_id}/accounts",
        json={"account_id": account_id},
    )
    assert r.status_code == 201, r.text
    # Первый аккаунт enabled-кампании → attach слушателя (раньше было нечем).
    assert pub.lifecycle() == [{"campaign_id": campaign_id, "action": ACTION_ATTACH}]


def test_attach_second_account_does_not_publish(session):
    _clean(session)
    campaign_id = _make_campaign(session)
    a1 = _make_account(session, status="pool")
    a2 = _make_account(session, status="pool")
    pub = _SpyPublisher()
    client = _client_with_publisher(session, pub)

    client.post(
        f"/modules/commenting/campaigns/{campaign_id}/accounts", json={"account_id": a1}
    )
    pub.events.clear()
    r = client.post(
        f"/modules/commenting/campaigns/{campaign_id}/accounts", json={"account_id": a2}
    )
    assert r.status_code == 201, r.text
    assert pub.lifecycle() == []           # слушатель уже подключён первым аккаунтом
