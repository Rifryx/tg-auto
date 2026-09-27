"""Промпт 2.6: dry-run режим.

Ключевое инвариантное свойство — при dry_run=true **ни одна** обёртка
Telethon не дёргается: ни ClientPool.get, ни client.get_input_entity,
ни client(request). Проверяем это как через TriggerRunner напрямую, так
и через executor.
"""

from __future__ import annotations

import itertools
import random
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("telethon")
pytest.importorskip("structlog")

from core.models import Account
from modules.priming.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
    ExecutionLogRepository,
)
from modules.priming.schemas.enums import (
    ExecutionOutcome,
    TargetStatus,
    TriggerAction,
)
from modules.priming.worker.executor import execute_prime
from modules.priming.worker.trigger import (
    DRY_RUN_DISTRIBUTION,
    TargetRef,
    TriggerRunner,
)


pytestmark = pytest.mark.asyncio


_PHONE = itertools.count(98_000_000_000)


# ---------------------------------------------------------------------------
# TriggerRunner.dry_run
# ---------------------------------------------------------------------------


async def test_dry_run_never_touches_client_or_governor() -> None:
    client = MagicMock(name="TelegramClient")
    client.get_input_entity = AsyncMock()
    governor = SimpleNamespace(check_and_reserve=AsyncMock())

    runner = TriggerRunner(
        client, governor, account_id=42, dry_run=True, rng=random.Random(0),
    )
    result = await runner.run(
        TriggerAction.SECRET_CHAT_REQUEST, TargetRef(username="alice"),
    )

    # Ни одного Telethon-обращения, ни одного вызова governor'а.
    client.get_input_entity.assert_not_awaited()
    client.assert_not_called()
    governor.check_and_reserve.assert_not_awaited()

    # Outcome — из распределения; пометка dry_run в meta.
    valid = {o for o, _ in DRY_RUN_DISTRIBUTION}
    assert result.outcome in valid
    assert result.meta.get("dry_run") is True


async def test_dry_run_distribution_is_stable_on_10000_rolls() -> None:
    """Пропорции по большому N совпадают с DRY_RUN_DISTRIBUTION в пределах 3%."""
    client = MagicMock(name="TelegramClient")
    client.get_input_entity = AsyncMock()
    governor = SimpleNamespace(check_and_reserve=AsyncMock())
    runner = TriggerRunner(
        client, governor, account_id=1, dry_run=True, rng=random.Random(42),
    )

    counts: dict[ExecutionOutcome, int] = {o: 0 for o, _ in DRY_RUN_DISTRIBUTION}
    N = 10_000
    for _ in range(N):
        r = await runner.run(TriggerAction.SECRET_CHAT_REQUEST, TargetRef(tg_user_id=1))
        counts[r.outcome] = counts.get(r.outcome, 0) + 1

    for outcome, expected_share in DRY_RUN_DISTRIBUTION:
        observed_share = counts[outcome] / N
        assert abs(observed_share - expected_share) < 0.03, (
            f"{outcome} share {observed_share} vs expected {expected_share}"
        )


# ---------------------------------------------------------------------------
# execute_prime в dry-run
# ---------------------------------------------------------------------------


def _factory(session):
    class _Ctx:
        def __enter__(self_inner): return session
        def __exit__(self_inner, *_): return False
    return lambda: _Ctx()


def _make_account(session) -> Account:
    a = Account(
        phone=str(next(_PHONE)), session_enc=b"x", status="pool",
        device_model="P", system_version="13", app_version="10",
        lang_code="ru", system_lang_code="ru-RU",
    )
    session.add(a)
    session.flush()
    return a


async def test_execute_prime_in_dry_run_skips_client_pool(session) -> None:
    campaign = CampaignRepository(session).create({
        "name": "c",
        "trigger_action": TriggerAction.SECRET_CHAT_REQUEST.value,
        "dry_run": True,
    })
    acc = _make_account(session)
    ca = CampaignAccountRepository(session).create({
        "campaign_id": campaign.id, "account_id": acc.id,
    })
    target = CampaignTargetRepository(session).create({
        "campaign_id": campaign.id, "username": "alice",
    })
    target.status = TargetStatus.ASSIGNED.value
    session.commit()

    pool = SimpleNamespace(get=AsyncMock(), release=AsyncMock())
    governor = SimpleNamespace(check_and_reserve=AsyncMock(return_value=True))
    ctx = {
        "session_factory": _factory(session),
        "client_pool": pool,
        "governor": governor,
    }

    result = await execute_prime(ctx, campaign.id, ca.id, target.id)
    assert result is not None

    # Pool не трогали.
    pool.get.assert_not_awaited()
    pool.release.assert_not_awaited()

    # execution_log отмечен dry_run=true.
    logs = ExecutionLogRepository(session).list_by_campaign(campaign.id)
    assert len(logs) == 1
    assert logs[0].dry_run is True
