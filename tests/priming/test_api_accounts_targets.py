"""Промпт 2.5: аккаунты и targets в API прайминга.

E2E через TestClient. Требуют postgres_test.
"""

from __future__ import annotations

import itertools
import io

import pytest

pytest.importorskip("telethon")
pytest.importorskip("structlog")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from core.models import Account
from core.repositories.subscription import SubscriptionRepository
from modules.priming.api.router import router as priming_router
from modules.priming.repositories import (
    BlacklistRepository,
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
)
from modules.priming.schemas.enums import (
    BlacklistReason,
    PrimingCampaignStatus,
    TargetStatus,
    TriggerAction,
)


_PHONE = itertools.count(97_000_000_000)


class _SpyTaskQueue:
    async def enqueue(self, *a, **k): return "job"
    async def schedule(self, *a, **k): return "job"


def _client(session):
    # Пейволл prompt 7.7: priming write-роуты требуют Pro-план.
    SubscriptionRepository(session).upsert("1", "pro")
    session.commit()
    app = FastAPI()
    app.include_router(priming_router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_user] = lambda: "1"
    app.dependency_overrides[get_task_queue] = lambda: _SpyTaskQueue()
    return TestClient(app)


def _acc(session) -> int:
    a = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="pool",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(a)
    session.flush()
    session.commit()
    return a.id


def _campaign(session, **overrides) -> int:
    payload = {
        "name": "c",
        "trigger_action": TriggerAction.SECRET_CHAT_REQUEST.value,
        "created_by": 1,
    }
    payload.update(overrides)
    c = CampaignRepository(session).create(payload)
    session.commit()
    return c.id


# ---------------------------------------------------------------------------
# Аккаунты
# ---------------------------------------------------------------------------

def test_attach_accounts_happy_path(session) -> None:
    api = _client(session)
    cid = _campaign(session)
    acc_ids = [_acc(session), _acc(session)]

    r = api.post(f"/modules/priming/campaigns/{cid}/accounts",
                 json={"account_ids": acc_ids})
    assert r.status_code == 200
    body = r.json()
    assert len(body["attached"]) == 2
    assert body["skipped_busy"] == []
    assert body["skipped_duplicate"] == []

    r = api.get(f"/modules/priming/campaigns/{cid}/accounts")
    assert len(r.json()) == 2


def test_attach_accounts_dedup_within_same_campaign(session) -> None:
    api = _client(session)
    cid = _campaign(session)
    account_id = _acc(session)

    api.post(f"/modules/priming/campaigns/{cid}/accounts",
             json={"account_ids": [account_id]})
    r = api.post(f"/modules/priming/campaigns/{cid}/accounts",
                 json={"account_ids": [account_id]})
    assert r.status_code == 200
    assert account_id in r.json()["skipped_duplicate"]


def test_attach_accounts_rejects_busy_elsewhere(session) -> None:
    api = _client(session)
    # Первая кампания получает аккаунт и переводится в running.
    running_cid = _campaign(session)
    account_id = _acc(session)
    api.post(f"/modules/priming/campaigns/{running_cid}/accounts",
             json={"account_ids": [account_id]})
    # Добавим цель, чтобы start прошёл валидацию.
    CampaignTargetRepository(session).create({
        "campaign_id": running_cid, "username": "u",
    })
    session.commit()
    assert api.post(f"/modules/priming/campaigns/{running_cid}/start").status_code == 200

    # Вторая кампания пытается забрать тот же account.
    other_cid = _campaign(session, name="other")
    r = api.post(f"/modules/priming/campaigns/{other_cid}/accounts",
                 json={"account_ids": [account_id]})
    assert r.status_code == 200
    assert r.json()["skipped_busy"] == [account_id]
    assert r.json()["attached"] == []


def test_attach_accounts_rejects_empty_list(session) -> None:
    api = _client(session)
    cid = _campaign(session)
    r = api.post(f"/modules/priming/campaigns/{cid}/accounts",
                 json={"account_ids": []})
    assert r.status_code == 422


def test_detach_account(session) -> None:
    api = _client(session)
    cid = _campaign(session)
    account_id = _acc(session)
    api.post(f"/modules/priming/campaigns/{cid}/accounts",
             json={"account_ids": [account_id]})

    r = api.delete(f"/modules/priming/campaigns/{cid}/accounts/{account_id}")
    assert r.status_code == 204

    r = api.get(f"/modules/priming/campaigns/{cid}/accounts")
    assert r.json() == []

    # Повтор — 404.
    r = api.delete(f"/modules/priming/campaigns/{cid}/accounts/{account_id}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Targets: JSON import
# ---------------------------------------------------------------------------

def test_import_targets_json(session) -> None:
    api = _client(session)
    cid = _campaign(session)

    payload = {"targets": [
        {"tg_user_id": 111, "username": "alice"},
        {"username": "@bob"},
        {"phone": "+79001234567"},
    ]}
    r = api.post(f"/modules/priming/campaigns/{cid}/targets/import", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inserted"] == 3
    assert body["skipped_duplicate"] == 0
    assert body["skipped_blacklisted"] == 0

    # Проверяем, что username нормализован (без @).
    targets = CampaignTargetRepository(session).list_by_campaign(cid)
    usernames = {t.username for t in targets if t.username}
    assert usernames == {"alice", "bob"}


def test_import_targets_dedupes_within_batch(session) -> None:
    api = _client(session)
    cid = _campaign(session)
    payload = {"targets": [
        {"tg_user_id": 111},
        {"tg_user_id": 111},
        {"tg_user_id": 111},
    ]}
    r = api.post(f"/modules/priming/campaigns/{cid}/targets/import", json=payload)
    body = r.json()
    assert body["inserted"] == 1
    assert body["skipped_duplicate"] == 2


def test_import_targets_dedupes_across_batches(session) -> None:
    api = _client(session)
    cid = _campaign(session)
    api.post(f"/modules/priming/campaigns/{cid}/targets/import",
             json={"targets": [{"tg_user_id": 111}]})
    r = api.post(f"/modules/priming/campaigns/{cid}/targets/import",
                 json={"targets": [{"tg_user_id": 111}, {"tg_user_id": 222}]})
    body = r.json()
    assert body["inserted"] == 1  # 111 отброшен ON CONFLICT
    assert body["skipped_duplicate"] == 1


def test_import_targets_respects_blacklist(session) -> None:
    api = _client(session)
    cid = _campaign(session)
    # Глобальный blacklist.
    BlacklistRepository(session).create({
        "owner_user_id": None, "tg_user_id": 999,
        "reason": BlacklistReason.MANUAL.value,
    })
    session.commit()
    payload = {"targets": [
        {"tg_user_id": 999},  # → blacklisted
        {"tg_user_id": 100},  # → OK
    ]}
    r = api.post(f"/modules/priming/campaigns/{cid}/targets/import", json=payload)
    body = r.json()
    assert body["inserted"] == 1
    assert body["skipped_blacklisted"] == 1


# ---------------------------------------------------------------------------
# Targets: CSV import
# ---------------------------------------------------------------------------

def test_import_targets_csv_with_empty_columns(session) -> None:
    api = _client(session)
    cid = _campaign(session)
    csv_text = "tg_user_id,username,phone\n"
    csv_text += "111,alice,\n"      # tg + username
    csv_text += ",bob,\n"           # только username
    csv_text += ",,+79000000000\n"  # только phone
    csv_text += ",,\n"              # пустая строка → skipped_invalid

    r = api.post(
        f"/modules/priming/campaigns/{cid}/targets/import",
        files={"file": ("targets.csv", io.BytesIO(csv_text.encode()), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inserted"] == 3
    assert body["skipped_invalid"] == 1


# ---------------------------------------------------------------------------
# List with status filter
# ---------------------------------------------------------------------------

def test_list_targets_filter_by_status(session) -> None:
    api = _client(session)
    cid = _campaign(session)
    t_repo = CampaignTargetRepository(session)
    p = t_repo.create({"campaign_id": cid, "username": "pending_one"})
    _ = t_repo.create({"campaign_id": cid, "username": "primed_one"})
    session.commit()
    _.status = TargetStatus.PRIMED.value
    session.flush()

    r = api.get(f"/modules/priming/campaigns/{cid}/targets?status=pending")
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()]
    assert ids == [p.id]


# ---------------------------------------------------------------------------
# Bulk blacklist
# ---------------------------------------------------------------------------

def test_bulk_blacklist_targets(session) -> None:
    api = _client(session)
    cid = _campaign(session)
    t1 = CampaignTargetRepository(session).create({
        "campaign_id": cid, "tg_user_id": 111,
    })
    t2 = CampaignTargetRepository(session).create({
        "campaign_id": cid, "tg_user_id": 222,
    })
    session.commit()

    r = api.post(
        f"/modules/priming/campaigns/{cid}/targets/blacklist",
        json={"target_ids": [t1.id, t2.id]},
    )
    assert r.status_code == 200
    assert r.json() == {"blacklisted": 2}

    # Проверяем состояние и записи в blacklist.
    for tid in (t1.id, t2.id):
        t = CampaignTargetRepository(session).get_by_id(tid)
        assert t.status == TargetStatus.BLACKLISTED.value

    bl = BlacklistRepository(session).list_by_owner(1)
    assert {row.tg_user_id for row in bl} == {111, 222}
