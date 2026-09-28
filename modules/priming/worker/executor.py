"""Executor одной попытки прайминга (spec §7.1, промпт 2.2).

Одна единица работы — «прайм цели X аккаунтом Y в кампании Z». Executor:

1. Читает кампанию, аккаунт кампании и цель.
2. Через :class:`worker.client_pool.ClientPool` получает Telethon-клиент.
3. Через :class:`TriggerRunner` (промпт 2.1) выполняет ``trigger_action``.
4. Логирует запись в ``priming.execution_log`` (append-only).
5. Обновляет счётчики ``campaign_accounts`` и статус цели.
6. При FLOOD_WAIT — пишет в ``priming.flood_incidents``, обновляет
   ``next_available_at`` и переводит аккаунт в quarantine, если счётчик
   подряд флудвейтов превысил лимит кампании.
7. Освобождает клиента.

Инъекции через ``ctx`` (для тестов):
``session_factory``, ``client_pool``, ``governor``, ``trigger_runner_factory``
(опционально; по умолчанию — обычный :class:`TriggerRunner`), ``now``,
``publisher`` (для health-событий).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import structlog

from modules.priming.models import (
    PrimingCampaign,
    PrimingCampaignAccount,
    PrimingCampaignTarget,
)
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
    TriggerRotationStrategy,
)
from modules.priming.worker.alerts import emit_priming_alert
from modules.priming.worker.quiet_hours import is_quiet_hour_for
from modules.priming.worker.rotation import pick_trigger_action
from modules.priming.worker.trigger import (
    GOVERNOR_ACTION_TYPE,
    TargetRef,
    TriggerResult,
    TriggerRunner,
)

get_logger = structlog.get_logger


# --- ctx helpers ------------------------------------------------------------


def _now(ctx: dict) -> datetime:
    return ctx.get("now") or datetime.now(timezone.utc)


def _pool(ctx: dict):
    return ctx["client_pool"]


def _governor(ctx: dict):
    return ctx["governor"]


def _trigger_runner_factory(
    ctx: dict,
) -> Callable[..., TriggerRunner]:
    """Возвращает фабрику ``(client, governor, account_id, *, dry_run)
    -> TriggerRunner``. Тесты могут подменить.
    """
    factory = ctx.get("trigger_runner_factory")
    if factory is not None:
        return factory

    def _default(client, governor, account_id, *, dry_run: bool = False):
        return TriggerRunner(
            client, governor, account_id=account_id, dry_run=dry_run,
        )

    return _default


# --- маппинг outcome → target status и cooldown -----------------------------

def _target_status_for(outcome: ExecutionOutcome) -> Optional[TargetStatus]:
    """Что вписываем в ``campaign_targets.status`` после попытки.

    ``None`` — цель НЕ трогаем (например, FLOOD_WAIT — виноват аккаунт,
    цель остаётся в ``assigned`` и подхватится ретраем orchestrator'а).
    """
    mapping: dict[ExecutionOutcome, Optional[TargetStatus]] = {
        ExecutionOutcome.PRIMED: TargetStatus.PRIMED,
        ExecutionOutcome.ALREADY_APPLIED: TargetStatus.PRIMED,
        ExecutionOutcome.PRIVACY_RESTRICTED: TargetStatus.SKIPPED,
        ExecutionOutcome.DELETED: TargetStatus.SKIPPED,
        ExecutionOutcome.NOT_FOUND: TargetStatus.SKIPPED,
        ExecutionOutcome.SKIPPED_QUIET: TargetStatus.SKIPPED,
        ExecutionOutcome.FLOOD_WAIT: None,
        ExecutionOutcome.CHANNEL_PINNED_ERROR: TargetStatus.FAILED,
        ExecutionOutcome.INTERNAL_ERROR: TargetStatus.FAILED,
    }
    return mapping.get(outcome, TargetStatus.FAILED)


# --- сама задача ------------------------------------------------------------


@dataclass
class ExecutePrimeResult:
    """Компактный ответ для тестов и логов. arq игнорирует возврат."""

    outcome: ExecutionOutcome
    latency_ms: int
    flood_wait_sec: Optional[int]
    quarantined: bool
    target_next_status: Optional[str]


async def execute_prime(
    ctx: dict,
    campaign_id: int,
    campaign_account_id: int,
    target_id: int,
) -> Optional[ExecutePrimeResult]:
    """Один прайм. Возвращает :class:`ExecutePrimeResult` или ``None``
    (если данные исчезли между планированием и стартом — идемпотентный no-op).
    """
    log = get_logger()
    session_factory = ctx["session_factory"]

    # 1. Читаем данные в короткоживущей сессии (клиент от неё не зависит).
    with session_factory() as session:
        campaign: Optional[PrimingCampaign] = CampaignRepository(session).get_by_id(
            campaign_id
        )
        ca_repo = CampaignAccountRepository(session)
        campaign_account: Optional[PrimingCampaignAccount] = ca_repo.get_by_id(
            campaign_account_id
        )
        target: Optional[PrimingCampaignTarget] = CampaignTargetRepository(
            session
        ).get_by_id(target_id)

        if campaign is None or campaign_account is None or target is None:
            log.warning(
                "priming.execute_prime.missing",
                campaign_id=campaign_id,
                campaign_account_id=campaign_account_id,
                target_id=target_id,
            )
            return None

        # Снимок нужных значений — сессия сейчас закроется.
        # trigger_action выбирается ЗДЕСЬ (в момент старта прайминга,
        # spec §7.1) через ротацию по списку кампании; фолбэк на старую
        # одиночную колонку — для кампаний, которые ещё не пере-
        # инициализированы (backfill сделал это, но подстраховка не мешает).
        actions_list = list(campaign.trigger_actions or [])
        if not actions_list and campaign.trigger_action:
            actions_list = [campaign.trigger_action]
        strategy = TriggerRotationStrategy(campaign.trigger_rotation_strategy)
        trigger_action = pick_trigger_action(
            actions_list, strategy,
            counter=campaign_account.primes_total,
        )
        flood_wait_pause_sec = campaign.flood_wait_pause_sec
        max_flood_waits = campaign.max_flood_waits_per_account
        dry_run = bool(campaign.dry_run)
        account_id = campaign_account.account_id
        target_ref = TargetRef(
            tg_user_id=target.tg_user_id,
            username=target.username,
            phone=target.phone,
        )
        quiet_hours_target = bool(getattr(campaign, "quiet_hours_target", False))
        quiet_hours_tz = getattr(campaign, "quiet_hours_tz", None)

    # 2. Тихие часы цели — до открытия клиента, чтобы не расходовать
    # квоту pool'а зря. Если известна TZ (пока — из кампании) и в ней
    # ночь (00:00–07:00), сразу отдаём SKIPPED_QUIET.
    pool = _pool(ctx)
    started_at = _now(ctx)
    if quiet_hours_target and is_quiet_hour_for(quiet_hours_tz, now=started_at):
        finished_at = started_at
        result = TriggerResult(
            outcome=ExecutionOutcome.SKIPPED_QUIET,
            latency_ms=0,
            error_code=None,
            flood_wait_sec=None,
        )
    else:
        client = None if dry_run else await pool.get(account_id)
        try:
            runner = _trigger_runner_factory(ctx)(
                client, _governor(ctx), account_id, dry_run=dry_run,
            )
            result = await runner.run(trigger_action, target_ref)
        finally:
            if not dry_run:
                await pool.release(account_id)
        finished_at = _now(ctx)

    outcome = result.outcome

    # 3. Пишем всё в БД одной короткой сессией.
    with session_factory() as session:
        ExecutionLogRepository(session).append(
            campaign_id=campaign_id,
            account_id=account_id,
            target_id=target_id,
            started_at=started_at,
            finished_at=finished_at,
            outcome=outcome.value,
            trigger_action=trigger_action.value,
            latency_ms=result.latency_ms,
            error_code=result.error_code,
            flood_wait_sec=result.flood_wait_sec,
            dry_run=dry_run,
        )

        quarantined = False
        ca_repo = CampaignAccountRepository(session)
        if outcome is ExecutionOutcome.FLOOD_WAIT:
            # Если flood_wait_sec неизвестен (governor self-throttle) — берём
            # штатную паузу кампании.
            wait_sec = result.flood_wait_sec or flood_wait_pause_sec
            FloodIncidentRepository(session).append(
                campaign_account_id=campaign_account_id,
                flood_wait_sec=wait_sec,
                endpoint=GOVERNOR_ACTION_TYPE,
                at=finished_at,
            )
            updated = ca_repo.release_after_prime(
                campaign_account_id,
                outcome=outcome.value,
                flood_wait_sec=wait_sec,
                now=finished_at,
            )
            # Проверка порога карантина.
            if updated is not None and updated.flood_waits_consecutive >= max_flood_waits:
                ca_repo.quarantine(campaign_account_id)
                quarantined = True
                log.warning(
                    "priming.execute_prime.quarantined",
                    campaign_id=campaign_id,
                    campaign_account_id=campaign_account_id,
                    consecutive=updated.flood_waits_consecutive,
                )
                emit_priming_alert(
                    ctx.get("publisher"), "quarantined",
                    campaign_id=campaign_id,
                    campaign_account_id=campaign_account_id,
                    account_id=account_id,
                    consecutive=updated.flood_waits_consecutive,
                )
        else:
            ca_repo.release_after_prime(
                campaign_account_id,
                outcome=outcome.value,
                now=finished_at,
            )

        # 4. Обновляем статус цели.
        next_status = _target_status_for(outcome)
        if next_status is not None:
            CampaignTargetRepository(session).mark_result(
                target_id,
                outcome_status=next_status,
                error_code=result.error_code,
                now=finished_at,
            )

        session.commit()

    return ExecutePrimeResult(
        outcome=outcome,
        latency_ms=result.latency_ms,
        flood_wait_sec=result.flood_wait_sec,
        quarantined=quarantined,
        target_next_status=(next_status.value if next_status else None),
    )
