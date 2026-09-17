"""Anti-Ban Predictor tasks (этап 11).

Извлекает фичи из существующих таблиц (HealthEvent, WarmingActivity,
AccountHealth, Account) и запускает rule-based predictor. Результат
сохраняется в ban_risk_snapshots и публикуется в pub/sub.

Задачи:
* ``health.predict_ban_risk`` — per-account prediction (вызывается после
  health.recompute_score или по запросу).
* ``health.predict_ban_risk_batch`` — cron, обходит все активные аккаунты.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select

from core.enums import AccountStatus, WarmingActivityStatus
from core.enums.health import HealthEventType
from core.enums.risk import RiskLevel
from core.models import Account, AccountHealth, HealthEvent, WarmingActivity
from core.predictor import RiskFeatures, predict_risk
from core.queue import TaskQueue
from core.queue.publisher import Publisher
from core.queue.task_names import TaskName
from core.repositories.account_health import AccountHealthRepository
from core.repositories.ban_risk import BanRiskRepository
from worker.tasks.logging import get_logger

BAN_RISK_CHANNEL = "health.ban_risk_updated"

_ACTIVE_STATUSES = (
    AccountStatus.POOL.value,
    AccountStatus.ASSIGNED.value,
    AccountStatus.WARMING.value,
    AccountStatus.COOLDOWN.value,
)


def _extract_features(session, account_id: int, now: datetime) -> RiskFeatures:
    """Extract prediction features from existing DB tables."""

    health = AccountHealthRepository(session).get(account_id)
    account = session.get(Account, account_id)

    # Health event counts by time window.
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    events = (
        session.execute(
            select(
                HealthEvent.event_type,
                HealthEvent.created_at,
                HealthEvent.resolved,
            )
            .where(HealthEvent.account_id == account_id)
            .where(HealthEvent.created_at >= cutoff_30d)
        )
        .all()
    )

    flood_24h = sum(
        1 for et, ts, _ in events
        if et == HealthEventType.FLOOD_WAIT.value and ts >= cutoff_24h
    )
    flood_7d = sum(
        1 for et, ts, _ in events
        if et == HealthEventType.FLOOD_WAIT.value and ts >= cutoff_7d
    )
    spam_7d = sum(
        1 for et, ts, _ in events
        if et == HealthEventType.SPAM_BLOCK.value and ts >= cutoff_7d
    )
    spam_30d = sum(
        1 for et, ts, _ in events
        if et == HealthEventType.SPAM_BLOCK.value
    )
    unresolved = sum(1 for _, _, resolved in events if not resolved)

    last_incident_ts = max(
        (ts for _, ts, _ in events), default=None
    )
    hours_since_last = None
    if last_incident_ts is not None:
        hours_since_last = (now - last_incident_ts).total_seconds() / 3600

    # Warming activity stats.
    activities_24h = (
        session.execute(
            select(WarmingActivity.status, WarmingActivity.action_type)
            .where(WarmingActivity.account_id == account_id)
            .where(WarmingActivity.created_at >= cutoff_24h)
        )
        .all()
    )
    total_24h = len(activities_24h)
    failed_24h = sum(
        1 for s, _ in activities_24h
        if s == WarmingActivityStatus.FAILED.value
    )

    activities_7d = (
        session.execute(
            select(WarmingActivity.status, WarmingActivity.action_type)
            .where(WarmingActivity.account_id == account_id)
            .where(WarmingActivity.created_at >= cutoff_7d)
        )
        .all()
    )
    total_7d = len(activities_7d)
    failed_7d = sum(
        1 for s, _ in activities_7d
        if s == WarmingActivityStatus.FAILED.value
    )
    unique_types_7d = len({at for _, at in activities_7d})

    fail_rate_24h = failed_24h / total_24h if total_24h > 0 else 0.0
    fail_rate_7d = failed_7d / total_7d if total_7d > 0 else 0.0
    actions_per_hour = total_24h / 24.0

    # Profile completeness.
    profile_score = 0
    if health:
        if health.has_2fa:
            profile_score += 1
        if health.has_username:
            profile_score += 1
        if health.has_avatar:
            profile_score += 1
        if health.has_bio:
            profile_score += 1

    age_days = None
    if account and account.created_at:
        age_days = max(0, (now - account.created_at).days)

    return RiskFeatures(
        flood_waits_24h=flood_24h,
        flood_waits_7d=flood_7d,
        spam_blocks_7d=spam_7d,
        spam_blocks_30d=spam_30d,
        action_fail_rate_24h=fail_rate_24h,
        action_fail_rate_7d=fail_rate_7d,
        actions_per_hour_24h=actions_per_hour,
        unique_action_types_7d=unique_types_7d,
        profile_completeness=profile_score,
        age_days=age_days,
        hours_since_last_incident=hours_since_last,
        unresolved_incidents=unresolved,
        session_alive=health.session_alive if health else None,
        phone_banned=(
            health.phone_status == "banned" if health else False
        ),
        current_health_score=(
            health.health_score if health else 100
        ),
    )


async def predict_ban_risk_impl(ctx: dict, account_id: int) -> dict[str, Any]:
    """Per-account ban risk prediction."""
    now = ctx.get("now") or datetime.now(timezone.utc)
    session_factory = ctx["session_factory"]
    publisher: Optional[Publisher] = ctx.get("publisher")

    with session_factory() as session:
        features = _extract_features(session, account_id, now)
        prediction = predict_risk(features)

        repo = BanRiskRepository(session)
        existing = repo.get(account_id)
        previous = existing.risk_score if existing else None

        repo.upsert(
            account_id,
            risk_score=prediction.risk_score,
            risk_level=prediction.risk_level.value,
            previous_risk_score=previous,
            features=features.__dict__,
            contributions=prediction.as_dict()["contributions"],
            computed_at=now,
        )
        session.commit()

    if publisher is not None:
        publisher.publish(
            BAN_RISK_CHANNEL,
            {
                "account_id": account_id,
                "risk_score": round(prediction.risk_score, 4),
                "risk_level": prediction.risk_level.value,
                "previous_risk_score": previous,
                "computed_at": now.isoformat(),
            },
        )

    get_logger().info(
        "health.predict_ban_risk.done",
        account_id=account_id,
        risk_score=round(prediction.risk_score, 4),
        risk_level=prediction.risk_level.value,
    )
    return prediction.as_dict()


async def predict_ban_risk_batch_impl(
    ctx: dict, *args: Any, **kwargs: Any
) -> dict[str, Any]:
    """Batch prediction for all active accounts (cron every 15 min)."""
    now = ctx.get("now") or datetime.now(timezone.utc)
    session_factory = ctx["session_factory"]
    queue = TaskQueue(redis=ctx.get("redis"))

    account_ids: list[int] = []
    with session_factory() as session:
        stmt = (
            select(Account.id)
            .where(Account.status.in_(_ACTIVE_STATUSES))
        )
        account_ids = [row[0] for row in session.execute(stmt).all()]

    for aid in account_ids:
        await queue.enqueue(TaskName.HEALTH_PREDICT_BAN_RISK, aid)

    get_logger().info(
        "health.predict_ban_risk_batch.done",
        enqueued=len(account_ids),
    )
    return {"enqueued": account_ids}
