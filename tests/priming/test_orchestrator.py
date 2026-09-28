"""Промпт 2.3: orchestrator_tick (DB под postgres_test, task_queue замокан).

Ветки:
* обычный tick раскладывает execute_prime по свободным аккаунтам и
  планирует следующий tick с задержкой из диапазона;
* тик пропускает quarantined-аккаунт;
* пустой пул (никого нельзя работать) — reschedule через 60 сек;
* автостоп по privacy_rate переводит кампанию в paused;
* тик на non-running кампании ничего не раздаёт.
"""

from __future__ import annotations

import itertools
import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# orchestrator тянет task_queue/redis-инфру; в окружениях без нужных deps
# скипаем целиком.
pytest.importorskip("structlog")
pytest.importorskip("telethon")

from core.models import Account
from core.queue.task_names import TaskName
from modules.priming.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
    ExecutionLogRepository,
)
from modules.priming.schemas.enums import (
    ExecutionOutcome,
    PrimingAccountState,
    PrimingCampaignStatus,
    TargetStatus,
    TriggerAction,
)
from modules.priming.worker.orchestrator import (
    IDLE_RETRY_SECONDS,
    orchestrator_tick,
)


pytestmark = pytest.mark.asyncio


_PHONE = itertools.count(95_000_000_000)


def _make_account(session) -> Account:
    acc = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="pool",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(acc)
    session.flush()
    return acc


def _make_running_campaign(session, **overrides):
    payload = {
        "name": "c",
        "trigger_action": TriggerAction.SECRET_CHAT_REQUEST.value,
        "delay_between_targets_sec_min": 60,
        "delay_between_targets_sec_max": 90,
        "daily_limit_per_account": 40,
        "stop_on_privacy_rate": 0.3,
        "status": PrimingCampaignStatus.RUNNING.value,
    }
    payload.update(overrides)
    return CampaignRepository(session).create(payload)


def _factory(session):
    class _Ctx:
        def __enter__(self_inner):
            return session
        def __exit__(self_inner, *_):
            return False
    return lambda: _Ctx()


class _SpyTaskQueue:
    """Захватывает всё, что оркестратор ставит в очередь."""
    def __init__(self):
        self.enqueued: list = []
        self.scheduled: list = []
    async def enqueue(self, name, *args, **kwargs):
        self.enqueued.append((name, args, kwargs))
    async def schedule(self, name, run_at, *args, **kwargs):
        self.scheduled.append((name, run_at, args, kwargs))


def _ctx(session_factory, *, now=None, rng_seed=42):
    return {
        "session_factory": session_factory,
        "task_queue": _SpyTaskQueue(),
        "rng": random.Random(rng_seed),
        "now": now or datetime.now(timezone.utc),
    }


# ---------------------------------------------------------------------------
# Раскладка
# ---------------------------------------------------------------------------

async def test_tick_schedules_execute_prime_per_pair(session) -> None:
    campaign = _make_running_campaign(session)
    ca_repo = CampaignAccountRepository(session)
    t_repo = CampaignTargetRepository(session)

    # 2 аккаунта, 3 цели.
    accs = [ca_repo.create({"campaign_id": campaign.id, "account_id": _make_account(session).id})
            for _ in range(2)]
    targets = [t_repo.create({"campaign_id": campaign.id, "username": f"u{i}"})
               for i in range(3)]
    session.commit()

    ctx = _ctx(_factory(session))
    result = await orchestrator_tick(ctx, campaign.id)

    # Оба аккаунта разобраны + одна цель осталась pending.
    assert result["scheduled"] == 2
    tq: _SpyTaskQueue = ctx["task_queue"]
    assert len(tq.enqueued) == 2
    for name, args, _ in tq.enqueued:
        assert name is TaskName.PRIMING_EXECUTE_PRIME
        assert args[0] == campaign.id  # campaign_id первым

    # Следующий tick запланирован в пределах [60, 90] сек — плюс между
    # праймами оркестратор ставит humanizer_beat'ы (по одному на аккаунт).
    tick_scheduled = [
        s for s in tq.scheduled if s[0] is TaskName.PRIMING_ORCHESTRATOR_TICK
    ]
    assert len(tick_scheduled) == 1
    _, run_at, args, _ = tick_scheduled[0]
    assert args == (campaign.id,)
    delta = (run_at - ctx["now"]).total_seconds()
    assert 60 <= delta <= 90


async def test_tick_skips_quarantined_accounts(session) -> None:
    campaign = _make_running_campaign(session)
    ca_repo = CampaignAccountRepository(session)
    good_acc = _make_account(session)
    bad_acc = _make_account(session)
    ca_repo.create({"campaign_id": campaign.id, "account_id": good_acc.id})
    ca_bad = ca_repo.create({"campaign_id": campaign.id, "account_id": bad_acc.id})
    ca_repo.quarantine(ca_bad.id)
    CampaignTargetRepository(session).create({
        "campaign_id": campaign.id, "username": "u",
    })
    session.commit()

    ctx = _ctx(_factory(session))
    result = await orchestrator_tick(ctx, campaign.id)
    assert result["scheduled"] == 1


# ---------------------------------------------------------------------------
# Idle path
# ---------------------------------------------------------------------------

async def test_tick_reschedules_when_no_work(session) -> None:
    # Кампания без аккаунтов и без целей.
    campaign = _make_running_campaign(session)
    session.commit()

    ctx = _ctx(_factory(session))
    result = await orchestrator_tick(ctx, campaign.id)

    tq: _SpyTaskQueue = ctx["task_queue"]
    assert tq.enqueued == []
    assert result["scheduled"] == 0
    assert result["idle"] is True
    # Следующий tick через 60 сек.
    _, run_at, _, _ = tq.scheduled[0]
    delta = (run_at - ctx["now"]).total_seconds()
    assert delta == IDLE_RETRY_SECONDS


async def test_tick_no_targets_returns_account_to_idle(session) -> None:
    campaign = _make_running_campaign(session)
    ca_repo = CampaignAccountRepository(session)
    acc = _make_account(session)
    ca = ca_repo.create({"campaign_id": campaign.id, "account_id": acc.id})
    session.commit()

    ctx = _ctx(_factory(session))
    result = await orchestrator_tick(ctx, campaign.id)
    assert result["scheduled"] == 0

    # Аккаунт должен остаться в idle (не залипнуть в working).
    session.expire_all()
    ca_after = ca_repo.get_by_id(ca.id)
    assert ca_after.state == PrimingAccountState.IDLE.value


# ---------------------------------------------------------------------------
# Автостоп
# ---------------------------------------------------------------------------

async def test_autopause_when_privacy_rate_exceeds_threshold(session) -> None:
    campaign = _make_running_campaign(session, stop_on_privacy_rate=0.5)
    acc = _make_account(session)
    ca = CampaignAccountRepository(session).create({
        "campaign_id": campaign.id, "account_id": acc.id,
    })
    target = CampaignTargetRepository(session).create({
        "campaign_id": campaign.id, "username": "u",
    })
    log_repo = ExecutionLogRepository(session)
    now = datetime.now(timezone.utc)
    # 30 попыток, 60% privacy_restricted — выше порога 50%.
    for i in range(30):
        log_repo.append(
            campaign_id=campaign.id, account_id=acc.id, target_id=target.id,
            started_at=now, finished_at=now,
            outcome=(
                ExecutionOutcome.PRIVACY_RESTRICTED.value if i < 18
                else ExecutionOutcome.PRIMED.value
            ),
            trigger_action=TriggerAction.SECRET_CHAT_REQUEST.value,
            latency_ms=10,
        )
    session.commit()

    ctx = _ctx(_factory(session))
    result = await orchestrator_tick(ctx, campaign.id)
    assert result["paused"] is True

    session.expire_all()
    campaign_after = CampaignRepository(session).get_by_id(campaign.id)
    assert campaign_after.status == PrimingCampaignStatus.PAUSED.value


async def test_autopause_ignores_small_samples(session) -> None:
    # Все 3 попытки privacy — но выборка ниже порога PRIVACY_RATE_MIN_SAMPLES.
    campaign = _make_running_campaign(session, stop_on_privacy_rate=0.1)
    acc = _make_account(session)
    CampaignAccountRepository(session).create({
        "campaign_id": campaign.id, "account_id": acc.id,
    })
    target = CampaignTargetRepository(session).create({
        "campaign_id": campaign.id, "username": "u",
    })
    log_repo = ExecutionLogRepository(session)
    now = datetime.now(timezone.utc)
    for _ in range(3):
        log_repo.append(
            campaign_id=campaign.id, account_id=acc.id, target_id=target.id,
            started_at=now, finished_at=now,
            outcome=ExecutionOutcome.PRIVACY_RESTRICTED.value,
            trigger_action=TriggerAction.SECRET_CHAT_REQUEST.value,
            latency_ms=1,
        )
    session.commit()

    ctx = _ctx(_factory(session))
    result = await orchestrator_tick(ctx, campaign.id)
    assert result["paused"] is False


# ---------------------------------------------------------------------------
# Non-running
# ---------------------------------------------------------------------------

async def test_tick_no_op_when_campaign_paused(session) -> None:
    campaign = _make_running_campaign(session, status=PrimingCampaignStatus.PAUSED.value)
    CampaignTargetRepository(session).create({
        "campaign_id": campaign.id, "username": "u",
    })
    session.commit()

    ctx = _ctx(_factory(session))
    result = await orchestrator_tick(ctx, campaign.id)
    assert result == {"scheduled": 0, "paused": False, "idle": True}
    tq: _SpyTaskQueue = ctx["task_queue"]
    assert tq.enqueued == []
    # Даже reschedule не делаем — тика больше не будет, пока не resume.
    assert tq.scheduled == []


async def test_tick_returns_none_on_missing_campaign(session) -> None:
    ctx = _ctx(_factory(session))
    assert await orchestrator_tick(ctx, 999_999) is None
