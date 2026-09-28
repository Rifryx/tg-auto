"""Orchestrator одной кампании прайминга (spec §7.1, промпт 2.3).

Одна tick-задача = ``priming.orchestrator_tick(campaign_id)``:

1. Проверяет статус кампании (только ``running`` → работаем).
2. Пока хватает свободных idle-аккаунтов и pending-целей:
   * ``acquire_next`` под FOR UPDATE SKIP LOCKED (idle→working);
   * ``claim_next`` под FOR UPDATE SKIP LOCKED (pending→assigned);
   * если цель не досталась — откатываем аккаунт в idle и выходим (
     дальше уже нечего раздавать);
   * планируем ``priming.execute_prime`` немедленно.
3. Планирует следующий tick через рандом-джиттер
   ``[delay_between_targets_sec_min .. _max]``.
4. Проверяет автостоп по ``stop_on_privacy_rate`` на скользящем окне
   200 записей ``execution_log``; при превышении — переводит кампанию
   в ``paused``.

Всё через ctx-инъекции — тестам не нужен ни Redis, ни таймер.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

from core.config.priming_warmup import (
    effective_daily_limit,
    effective_delay_range,
)
from core.queue import TaskQueue
from core.queue.task_names import TaskName
from modules.priming.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
    ExecutionLogRepository,
)
from modules.priming.schemas.enums import (
    ExecutionOutcome,
    HumanizerMode,
    PrimingAccountState,
    PrimingCampaignStatus,
)

get_logger = structlog.get_logger


# Пока нет пары (аккаунт, цель) — откладываем tick на минуту.
IDLE_RETRY_SECONDS = 60

# На сколько последних outcome'ов смотрим при расчёте privacy_rate.
PRIVACY_RATE_WINDOW = 200

# Минимум записей, чтобы вообще применять правило автостопа.
PRIVACY_RATE_MIN_SAMPLES = 20


# --- ctx helpers ------------------------------------------------------------

def _now(ctx: dict) -> datetime:
    return ctx.get("now") or datetime.now(timezone.utc)


def _rng(ctx: dict) -> random.Random:
    return ctx.get("rng") or random.Random()


def _task_queue(ctx: dict) -> TaskQueue:
    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


# --- ядро -------------------------------------------------------------------


async def orchestrator_tick(ctx: dict, campaign_id: int) -> Optional[dict]:
    """Один tick оркестратора кампании.

    Возвращает компактный отчёт для тестов и логов (arq игнорирует возврат):
    ``{scheduled: int, paused: bool, idle: bool}``.
    """
    log = get_logger()
    session_factory = ctx["session_factory"]
    task_queue = _task_queue(ctx)
    now = _now(ctx)
    rng = _rng(ctx)

    with session_factory() as session:
        campaign = CampaignRepository(session).get_by_id(campaign_id)
        if campaign is None:
            return None
        if campaign.status != PrimingCampaignStatus.RUNNING.value:
            log.info(
                "priming.orchestrator_tick.not_running",
                campaign_id=campaign_id,
                status=campaign.status,
            )
            return {"scheduled": 0, "paused": False, "idle": True}

        # Автостоп по privacy_rate (перед раскладкой — если сработает,
        # смысла раздавать новые праймы нет).
        if _should_autopause_privacy(session, campaign_id, campaign.stop_on_privacy_rate):
            CampaignRepository(session).set_status(
                campaign_id, PrimingCampaignStatus.PAUSED.value,
            )
            session.commit()
            log.warning(
                "priming.orchestrator_tick.autopause.privacy",
                campaign_id=campaign_id,
            )
            return {"scheduled": 0, "paused": True, "idle": False}

        # Снимок значений кампании — сессия сейчас закроется.
        # daily_limit — это КЭП кампании; фактический лимит на аккаунт
        # считается по warmup-профилю ниже (prompt 6.1).
        daily_limit = campaign.daily_limit_per_account
        warmup_profile = campaign.warmup_profile
        # Диапазон задержек: если у кампании стандартные значения профиля
        # (её сгенерил wizard), берём их; иначе — уже пользовательские.
        delay_min = campaign.delay_between_targets_sec_min
        delay_max = campaign.delay_between_targets_sec_max
        # Диапазон профиля используется только как страховочный дефолт,
        # если кампания вдруг сохранила невалидную пару (min > max) —
        # прод-путь берёт значения из кампании.
        prof_min, prof_max = effective_delay_range(warmup_profile)
        if delay_min > delay_max:
            delay_min, delay_max = prof_min, prof_max
        humanizer_mode = HumanizerMode(campaign.humanizer_mode)

    scheduled = 0
    idle = False
    while True:
        # Каждую пару (аккаунт, цель) выбираем в отдельной короткой сессии,
        # чтобы FOR UPDATE SKIP LOCKED не держал строки долго.
        with session_factory() as session:
            ca_repo = CampaignAccountRepository(session)
            acquired = ca_repo.acquire_next(
                campaign_id, daily_limit=daily_limit, now=now
            )
            if acquired is None:
                idle = True
                session.commit()
                break

            # Warmup-рампа: эффективный дневной лимит на КОНКРЕТНЫЙ
            # аккаунт с его warmup_started_at и профилем кампании.
            # Если аккаунт уже упёрся в него — вернуть в idle и
            # попробовать следующего (пусть на этом тике он не работает).
            eff_limit = effective_daily_limit(
                warmup_profile,
                acquired.warmup_started_at,
                now,
                campaign_cap=daily_limit,
            )
            if acquired.primes_today >= eff_limit:
                ca_repo.update(acquired.id, {
                    "state": PrimingAccountState.IDLE.value,
                })
                session.commit()
                continue

            # Первый прайм в этой кампании — фиксируем стартовую точку
            # рампы. Дальше warmup_started_at не сдвигается.
            if acquired.warmup_started_at is None:
                ca_repo.update(acquired.id, {"warmup_started_at": now})

            target = CampaignTargetRepository(session).claim_next(
                campaign_id, acquired.account_id
            )
            if target is None:
                # Целей нет — возвращаем аккаунт в idle и выходим.
                ca_repo.update(acquired.id, {
                    "state": PrimingAccountState.IDLE.value,
                })
                session.commit()
                break

            campaign_account_id = acquired.id
            target_id = target.id
            session.commit()

        await task_queue.enqueue(
            TaskName.PRIMING_EXECUTE_PRIME,
            campaign_id,
            campaign_account_id,
            target_id,
        )
        scheduled += 1

        # Humanizer beat в паузе. Планируем с случайной микро-задержкой в
        # пределах delay-диапазона — так beat приземлится ПОСЛЕ execute_prime
        # (тот держит state=working) и humanizer сам сделает no-op, если
        # аккаунт всё ещё занят.
        if humanizer_mode is not HumanizerMode.OFF:
            beat_at = now + timedelta(
                seconds=rng.randint(max(1, delay_min // 3), max(1, delay_max // 2))
            )
            await task_queue.schedule(
                TaskName.PRIMING_HUMANIZER_BEAT,
                beat_at, campaign_id, campaign_account_id,
            )

    # Планируем следующий tick с рандом-джиттером (или через IDLE_RETRY_SECONDS,
    # если совсем нечего раздавать).
    delay = (
        IDLE_RETRY_SECONDS
        if scheduled == 0
        else rng.randint(delay_min, delay_max)
    )
    await task_queue.schedule(
        TaskName.PRIMING_ORCHESTRATOR_TICK,
        now + timedelta(seconds=delay),
        campaign_id,
    )

    return {"scheduled": scheduled, "paused": False, "idle": idle}


# --- автостоп по privacy_rate -----------------------------------------------

def _should_autopause_privacy(
    session, campaign_id: int, stop_on_privacy_rate: float
) -> bool:
    """Возвращает True, если доля PRIVACY_RESTRICTED в последних N попытках
    превысила порог (и выборка достаточно большая, чтобы это не был шум).
    """
    outcomes = ExecutionLogRepository(session).recent_outcomes(
        campaign_id, window=PRIVACY_RATE_WINDOW,
    )
    if len(outcomes) < PRIVACY_RATE_MIN_SAMPLES:
        return False
    privacy = sum(
        1 for o in outcomes if o == ExecutionOutcome.PRIVACY_RESTRICTED.value
    )
    rate = privacy / len(outcomes)
    return rate > stop_on_privacy_rate
