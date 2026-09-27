"""DB-тесты репозиториев модуля прайминга (промпт 1.5).

Требуют поднятого postgres_test (см. общий conftest). Ключевые операции:
``acquire_next`` / ``claim_next`` — с FOR UPDATE SKIP LOCKED,
``ExecutionLogRepository.append`` (append-only + recent_outcomes),
``BlacklistRepository.match`` (owner + global).

Транзакция откатывается фикстурой ``session``, поэтому тесты не пачкают БД.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

import pytest

from core.models import Account
from modules.priming.repositories import (
    BlacklistRepository,
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
    ExecutionLogRepository,
    FloodIncidentRepository,
)
from modules.priming.schemas.enums import (
    BlacklistReason,
    ExecutionOutcome,
    PrimingAccountState,
    TargetStatus,
    TriggerAction,
)


_PHONE = itertools.count(93_000_000_000)


def _make_account(session) -> Account:
    acc = Account(
        phone=str(next(_PHONE)),
        session_enc=b"x",
        status="pool",
        device_model="P",
        system_version="13",
        app_version="10",
        lang_code="ru",
        system_lang_code="ru-RU",
    )
    session.add(acc)
    session.flush()
    return acc


def _make_campaign(session) -> int:
    repo = CampaignRepository(session)
    campaign = repo.create(
        {
            "name": "test",
            "trigger_action": TriggerAction.SECRET_CHAT_REQUEST.value,
            "delay_between_targets_sec_min": 60,
            "delay_between_targets_sec_max": 180,
        }
    )
    return campaign.id


# ---------------------------------------------------------------------------
# CampaignAccountRepository.acquire_next
# ---------------------------------------------------------------------------

def test_acquire_next_picks_idle_within_daily_limit(session) -> None:
    campaign_id = _make_campaign(session)
    accounts = [_make_account(session) for _ in range(2)]
    ca_repo = CampaignAccountRepository(session)
    a1 = ca_repo.create({"campaign_id": campaign_id, "account_id": accounts[0].id})
    a2 = ca_repo.create({"campaign_id": campaign_id, "account_id": accounts[1].id})
    session.flush()

    first = ca_repo.acquire_next(campaign_id, daily_limit=40)
    assert first is not None
    assert first.state == PrimingAccountState.WORKING.value

    # Второй acquire отдаст оставшийся idle-аккаунт.
    second = ca_repo.acquire_next(campaign_id, daily_limit=40)
    assert second is not None
    assert second.id != first.id

    # Третий — None, все заняты.
    assert ca_repo.acquire_next(campaign_id, daily_limit=40) is None


def test_acquire_next_respects_next_available_at(session) -> None:
    campaign_id = _make_campaign(session)
    acc = _make_account(session)
    ca_repo = CampaignAccountRepository(session)
    ca = ca_repo.create({"campaign_id": campaign_id, "account_id": acc.id})
    ca.next_available_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    session.flush()
    assert ca_repo.acquire_next(campaign_id, daily_limit=40) is None


def test_acquire_next_skips_quarantined(session) -> None:
    campaign_id = _make_campaign(session)
    acc = _make_account(session)
    ca_repo = CampaignAccountRepository(session)
    ca = ca_repo.create({"campaign_id": campaign_id, "account_id": acc.id})
    ca_repo.quarantine(ca.id)
    assert ca_repo.acquire_next(campaign_id, daily_limit=40) is None


def test_release_after_prime_updates_counters(session) -> None:
    campaign_id = _make_campaign(session)
    acc = _make_account(session)
    ca_repo = CampaignAccountRepository(session)
    ca = ca_repo.create({"campaign_id": campaign_id, "account_id": acc.id})
    acquired = ca_repo.acquire_next(campaign_id, daily_limit=40)
    assert acquired is not None

    updated = ca_repo.release_after_prime(acquired.id, outcome="primed")
    assert updated.primes_today == 1
    assert updated.primes_total == 1
    assert updated.flood_waits_consecutive == 0
    assert updated.state == PrimingAccountState.IDLE.value


def test_release_after_flood_wait_sets_cooldown(session) -> None:
    campaign_id = _make_campaign(session)
    acc = _make_account(session)
    ca_repo = CampaignAccountRepository(session)
    ca = ca_repo.create({"campaign_id": campaign_id, "account_id": acc.id})
    acquired = ca_repo.acquire_next(campaign_id, daily_limit=40)
    updated = ca_repo.release_after_prime(
        acquired.id, outcome="flood_wait", flood_wait_sec=500,
    )
    assert updated.flood_waits_consecutive == 1
    assert updated.flood_waits_total == 1
    assert updated.state == PrimingAccountState.COOLDOWN.value
    assert updated.next_available_at is not None


# ---------------------------------------------------------------------------
# CampaignTargetRepository.claim_next
# ---------------------------------------------------------------------------

def test_claim_next_transitions_pending_to_assigned(session) -> None:
    campaign_id = _make_campaign(session)
    acc = _make_account(session)
    t_repo = CampaignTargetRepository(session)
    t1 = t_repo.create({"campaign_id": campaign_id, "username": "alice"})
    t2 = t_repo.create({"campaign_id": campaign_id, "username": "bob"})
    session.flush()

    first = t_repo.claim_next(campaign_id, acc.id)
    assert first is not None
    assert first.status == TargetStatus.ASSIGNED.value
    assert first.assigned_account_id == acc.id
    assert first.attempts == 1

    second = t_repo.claim_next(campaign_id, acc.id)
    assert second is not None
    assert {t1.id, t2.id} == {first.id, second.id}

    # Больше pending нет.
    assert t_repo.claim_next(campaign_id, acc.id) is None


def test_bulk_create_dedupes_on_tg_user_id(session) -> None:
    campaign_id = _make_campaign(session)
    t_repo = CampaignTargetRepository(session)
    rows = [
        {"tg_user_id": 111, "username": "a"},
        {"tg_user_id": 222, "username": "b"},
        {"tg_user_id": 111, "username": "a_dup"},  # дубль по (campaign_id, tg_user_id)
    ]
    inserted = t_repo.bulk_create(campaign_id, rows)
    assert inserted == 2

    all_targets = t_repo.list_by_campaign(campaign_id)
    assert len(all_targets) == 2


def test_mark_result_primed_sets_primed_at(session) -> None:
    campaign_id = _make_campaign(session)
    acc = _make_account(session)
    t_repo = CampaignTargetRepository(session)
    t = t_repo.create({"campaign_id": campaign_id, "username": "alice"})
    claimed = t_repo.claim_next(campaign_id, acc.id)
    updated = t_repo.mark_result(claimed.id, outcome_status=TargetStatus.PRIMED)
    assert updated.status == TargetStatus.PRIMED.value
    assert updated.primed_at is not None


def test_transition_status_rejects_forbidden(session) -> None:
    campaign_id = _make_campaign(session)
    t_repo = CampaignTargetRepository(session)
    t = t_repo.create({"campaign_id": campaign_id, "username": "alice"})
    # PENDING → PRIMED напрямую запрещён (нужен ASSIGNED сначала).
    with pytest.raises(ValueError):
        t_repo.transition_status(t.id, next_status=TargetStatus.PRIMED)


# ---------------------------------------------------------------------------
# ExecutionLogRepository.append
# ---------------------------------------------------------------------------

def test_execution_log_append_and_recent_outcomes(session) -> None:
    campaign_id = _make_campaign(session)
    acc = _make_account(session)
    t_repo = CampaignTargetRepository(session)
    t = t_repo.create({"campaign_id": campaign_id, "username": "alice"})
    log_repo = ExecutionLogRepository(session)

    now = datetime.now(timezone.utc)
    log_repo.append(
        campaign_id=campaign_id,
        account_id=acc.id,
        target_id=t.id,
        started_at=now,
        finished_at=now + timedelta(milliseconds=200),
        outcome=ExecutionOutcome.PRIMED.value,
        trigger_action=TriggerAction.SECRET_CHAT_REQUEST.value,
        latency_ms=200,
    )
    log_repo.append(
        campaign_id=campaign_id,
        account_id=acc.id,
        target_id=t.id,
        started_at=now,
        finished_at=now,
        outcome=ExecutionOutcome.FLOOD_WAIT.value,
        trigger_action=TriggerAction.SECRET_CHAT_REQUEST.value,
        latency_ms=10,
        flood_wait_sec=500,
    )

    outcomes = log_repo.recent_outcomes(campaign_id, window=10)
    # Порядок «от новых к старым».
    assert outcomes == [
        ExecutionOutcome.FLOOD_WAIT.value,
        ExecutionOutcome.PRIMED.value,
    ]


# ---------------------------------------------------------------------------
# FloodIncidentRepository
# ---------------------------------------------------------------------------

def test_flood_incident_append(session) -> None:
    campaign_id = _make_campaign(session)
    acc = _make_account(session)
    ca_repo = CampaignAccountRepository(session)
    ca = ca_repo.create({"campaign_id": campaign_id, "account_id": acc.id})
    fi_repo = FloodIncidentRepository(session)
    fi_repo.append(
        campaign_account_id=ca.id,
        flood_wait_sec=500,
        endpoint="messages.RequestEncryption",
    )
    incidents = fi_repo.list_by_campaign_account(ca.id)
    assert len(incidents) == 1
    assert incidents[0].flood_wait_sec == 500


# ---------------------------------------------------------------------------
# BlacklistRepository.match
# ---------------------------------------------------------------------------

def test_blacklist_match_matches_owner_and_global(session) -> None:
    bl_repo = BlacklistRepository(session)
    bl_repo.create({
        "owner_user_id": 42,
        "tg_user_id": 555,
        "reason": BlacklistReason.MANUAL.value,
    })
    bl_repo.create({
        "owner_user_id": None,  # глобальный
        "username": "shady_bot",
        "reason": BlacklistReason.COMPLAINT.value,
    })
    session.flush()

    # Собственный blacklist пользователя.
    hit = bl_repo.match(owner_user_id=42, tg_user_id=555)
    assert hit is not None and hit.tg_user_id == 555

    # Глобальный сработает для любого пользователя.
    hit_global = bl_repo.match(owner_user_id=999, username="shady_bot")
    assert hit_global is not None

    # Чужой blacklist не сработает.
    miss = bl_repo.match(owner_user_id=100, tg_user_id=555)
    assert miss is None


def test_blacklist_match_requires_key(session) -> None:
    bl_repo = BlacklistRepository(session)
    # Без ключей поиска match возвращает None.
    assert bl_repo.match(owner_user_id=1) is None
