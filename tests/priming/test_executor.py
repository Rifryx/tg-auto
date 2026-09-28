"""Промпт 2.2: execute_prime (DB под postgres_test, TriggerRunner замокан).

Проверяем ветки: happy path (PRIMED), FLOOD_WAIT (обновление cooldown +
запись flood_incidents), quarantine после max_flood_waits, privacy →
target.SKIPPED, no-op при пропавших данных.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# executor тянет trigger → telethon; в окружениях без него скипаем целиком.
pytest.importorskip("telethon")
pytest.importorskip("structlog")

from core.models import Account
from modules.priming.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
    ExecutionLogRepository,
    FloodIncidentRepository,
)
from modules.priming.schemas.enums import (
    ExecutionOutcome,
    PrimingAccountState,
    TargetStatus,
    TriggerAction,
)
from modules.priming.worker.executor import execute_prime
from modules.priming.worker.trigger import TriggerResult


pytestmark = pytest.mark.asyncio


_PHONE = itertools.count(94_000_000_000)


def _make_account(session) -> Account:
    acc = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="pool",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(acc)
    session.flush()
    return acc


def _setup(session, *, max_flood_waits: int = 3):
    campaign = CampaignRepository(session).create({
        "name": "c",
        "trigger_action": TriggerAction.SECRET_CHAT_REQUEST.value,
        "trigger_actions": [TriggerAction.SECRET_CHAT_REQUEST.value],
        "max_flood_waits_per_account": max_flood_waits,
        "flood_wait_pause_sec": 500,
    })
    acc = _make_account(session)
    ca = CampaignAccountRepository(session).create({
        "campaign_id": campaign.id, "account_id": acc.id,
    })
    target = CampaignTargetRepository(session).create({
        "campaign_id": campaign.id, "username": "alice",
    })
    # Цель должна быть в assigned до executor'а (это работа orchestrator'а).
    target.status = TargetStatus.ASSIGNED.value
    session.flush()
    return SimpleNamespace(
        campaign_id=campaign.id, account_id=acc.id,
        campaign_account_id=ca.id, target_id=target.id,
    )


def _ctx(session_factory, *, trigger_result: TriggerResult):
    """Собирает ctx: клиент-пул как AsyncMock, TriggerRunner-фабрика возвращает
    заранее подготовленный TriggerResult без реального Telethon.
    """
    pool = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(name="client")),
        release=AsyncMock(),
    )
    governor = SimpleNamespace(check_and_reserve=AsyncMock(return_value=True))

    class _StubRunner:
        def __init__(self, client, gov, account_id, *, dry_run: bool = False):
            self._account_id = account_id
            self._dry_run = dry_run
        async def run(self, action, target):
            return trigger_result

    return {
        "session_factory": session_factory,
        "client_pool": pool,
        "governor": governor,
        "trigger_runner_factory": _StubRunner,
    }


def _factory(session):
    class _Ctx:
        def __enter__(self_inner):
            return session
        def __exit__(self_inner, *_):
            return False
    return lambda: _Ctx()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

async def test_primed_updates_counters_and_target(session) -> None:
    sut = _setup(session)
    ctx = _ctx(_factory(session), trigger_result=TriggerResult(
        outcome=ExecutionOutcome.PRIMED, latency_ms=150,
    ))

    result = await execute_prime(
        ctx, sut.campaign_id, sut.campaign_account_id, sut.target_id,
    )
    assert result is not None
    assert result.outcome is ExecutionOutcome.PRIMED
    assert result.quarantined is False
    assert result.target_next_status == TargetStatus.PRIMED.value

    # ExecutionLog создан.
    logs = ExecutionLogRepository(session).list_by_campaign(sut.campaign_id)
    assert len(logs) == 1
    assert logs[0].outcome == ExecutionOutcome.PRIMED.value
    assert logs[0].latency_ms == 150

    # Cчётчик primed поднялся, состояние idle, next_available_at не выставлен.
    ca = CampaignAccountRepository(session).get_by_id(sut.campaign_account_id)
    assert ca.primes_today == 1
    assert ca.primes_total == 1
    assert ca.flood_waits_consecutive == 0
    assert ca.state == PrimingAccountState.IDLE.value

    # Цель — primed + primed_at выставлен.
    target = CampaignTargetRepository(session).get_by_id(sut.target_id)
    assert target.status == TargetStatus.PRIMED.value
    assert target.primed_at is not None


# ---------------------------------------------------------------------------
# FLOOD_WAIT
# ---------------------------------------------------------------------------

async def test_flood_wait_writes_incident_and_cooldown(session) -> None:
    sut = _setup(session, max_flood_waits=3)
    ctx = _ctx(_factory(session), trigger_result=TriggerResult(
        outcome=ExecutionOutcome.FLOOD_WAIT,
        latency_ms=50,
        flood_wait_sec=42,
        error_code="FloodWaitError",
    ))

    result = await execute_prime(
        ctx, sut.campaign_id, sut.campaign_account_id, sut.target_id,
    )
    assert result.outcome is ExecutionOutcome.FLOOD_WAIT
    assert result.quarantined is False
    # Цель остаётся в assigned (мы не «съедаем» её из-за флуда на аккаунте).
    assert result.target_next_status is None

    # flood_incident одна.
    incidents = FloodIncidentRepository(session).list_by_campaign_account(
        sut.campaign_account_id,
    )
    assert len(incidents) == 1
    assert incidents[0].flood_wait_sec == 42

    ca = CampaignAccountRepository(session).get_by_id(sut.campaign_account_id)
    assert ca.state == PrimingAccountState.COOLDOWN.value
    assert ca.flood_waits_consecutive == 1
    assert ca.next_available_at is not None

    # Цель по-прежнему assigned.
    target = CampaignTargetRepository(session).get_by_id(sut.target_id)
    assert target.status == TargetStatus.ASSIGNED.value


async def test_flood_wait_quarantines_after_threshold(session) -> None:
    sut = _setup(session, max_flood_waits=2)
    # Заранее делаем 1 «подряд флудвейт», чтобы второй сработал как порог.
    CampaignAccountRepository(session).update(sut.campaign_account_id, {
        "flood_waits_consecutive": 1,
        "flood_waits_total": 1,
    })
    session.flush()

    ctx = _ctx(_factory(session), trigger_result=TriggerResult(
        outcome=ExecutionOutcome.FLOOD_WAIT, latency_ms=50, flood_wait_sec=60,
    ))
    result = await execute_prime(
        ctx, sut.campaign_id, sut.campaign_account_id, sut.target_id,
    )
    assert result.quarantined is True

    ca = CampaignAccountRepository(session).get_by_id(sut.campaign_account_id)
    assert ca.state == PrimingAccountState.QUARANTINED.value


# ---------------------------------------------------------------------------
# PRIVACY_RESTRICTED
# ---------------------------------------------------------------------------

async def test_privacy_marks_target_skipped(session) -> None:
    sut = _setup(session)
    ctx = _ctx(_factory(session), trigger_result=TriggerResult(
        outcome=ExecutionOutcome.PRIVACY_RESTRICTED,
        latency_ms=10,
        error_code="UserPrivacyRestrictedError",
    ))
    result = await execute_prime(
        ctx, sut.campaign_id, sut.campaign_account_id, sut.target_id,
    )
    assert result.target_next_status == TargetStatus.SKIPPED.value
    target = CampaignTargetRepository(session).get_by_id(sut.target_id)
    assert target.status == TargetStatus.SKIPPED.value
    assert target.last_error_code == "UserPrivacyRestrictedError"


# ---------------------------------------------------------------------------
# Missing data
# ---------------------------------------------------------------------------

async def test_no_op_on_missing_target(session) -> None:
    sut = _setup(session)
    ctx = _ctx(_factory(session), trigger_result=TriggerResult(
        outcome=ExecutionOutcome.PRIMED, latency_ms=1,
    ))
    result = await execute_prime(
        ctx, sut.campaign_id, sut.campaign_account_id, target_id=999_999,
    )
    assert result is None
    # Никакие Telethon/pool не вызывались.
    ctx["client_pool"].get.assert_not_awaited()
