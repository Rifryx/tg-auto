"""Сервис экрана «Главная» (PROJECT-STAGES §10).

Собирает весь дашборд минимумом запросов (агрегаты + один UNION на ленту, без
N+1) и кэширует результат в Redis на 5 секунд по ключу пользователя.

Реестра модулей ещё нет (отложен), поэтому список модулей захардкожен: пока
единственный модуль — ``commenting``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import redis
from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session

from core.config import get_settings
from core.enums import HealthEventType
from core.models import (
    Account,
    CampaignAccount,
    CommentLog,
    HealthEvent,
    WarmingActivity,
)

CACHE_TTL_SECONDS = 5
_CACHE_KEY = "monitoring:dashboard:{user_id}"

_ACCOUNT_STATUSES = (
    "created",
    "warming",
    "pool",
    "assigned",
    "cooldown",
    "retired",
    "banned",
)

# severity деривируется из типа события (отдельной колонки нет — §1.3/§5.3).
_SEVERITY: dict[str, str] = {
    HealthEventType.FLOOD_WAIT.value: "warning",
    HealthEventType.PROXY_DOWN.value: "warning",
    HealthEventType.RESTRICTED.value: "critical",
    HealthEventType.SPAM_BLOCK.value: "critical",
    HealthEventType.SESSION_REVOKED.value: "critical",
    HealthEventType.AUTH_FAILED.value: "critical",
}
_ALERTS_LIMIT = 20
_ACTIVITY_LIMIT = 30


def get_cache_redis() -> redis.Redis:
    """Клиент Redis для кэша дашборда (переопределяется в тестах)."""
    return redis.Redis.from_url(get_settings().redis_url)


def _event_types_for_severity(severity: str) -> list[str]:
    return [etype for etype, sev in _SEVERITY.items() if sev == severity]


def _alerts(session: Session, severity: Optional[str]) -> list[dict[str, Any]]:
    stmt = (
        select(
            HealthEvent.id,
            HealthEvent.account_id,
            Account.phone,
            HealthEvent.event_type,
            HealthEvent.created_at,
            HealthEvent.meta,
        )
        .join(Account, Account.id == HealthEvent.account_id)
        .where(HealthEvent.resolved.is_(False))
    )
    if severity is not None:
        stmt = stmt.where(HealthEvent.event_type.in_(_event_types_for_severity(severity)))
    stmt = stmt.order_by(HealthEvent.created_at.desc(), HealthEvent.id.desc()).limit(
        _ALERTS_LIMIT
    )
    rows = session.execute(stmt).all()
    items = [
        {
            "id": r.id,
            "account_id": r.account_id,
            "phone": r.phone,
            "event_type": r.event_type,
            "severity": _SEVERITY.get(r.event_type, "warning"),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "meta": r.meta,
        }
        for r in rows
    ]
    if severity in (None, "warning"):
        items += _channel_alerts(session)
        items.sort(key=lambda a: a["created_at"] or "", reverse=True)
        items = items[:_ALERTS_LIMIT]
    return items


# Открытые алерты целевых каналов нейрокомментинга (E3.2). «Подписали сами»
# на главной не показываем — это не требует действий (уходит только пушем).
_CHANNEL_ALERT_KINDS_ON_DASHBOARD = ("not_subscribed", "access_lost", "blacklisted")


def _channel_alerts(session: Session) -> list[dict[str, Any]]:
    from modules.commenting.models import ChannelAlert

    rows = session.execute(
        select(
            ChannelAlert.id,
            ChannelAlert.account_id,
            Account.phone,
            ChannelAlert.kind,
            ChannelAlert.created_at,
            ChannelAlert.campaign_id,
            ChannelAlert.channel_ref,
            ChannelAlert.detail,
        )
        .join(Account, Account.id == ChannelAlert.account_id)
        .where(
            ChannelAlert.resolved.is_(False),
            ChannelAlert.kind.in_(_CHANNEL_ALERT_KINDS_ON_DASHBOARD),
        )
        .order_by(ChannelAlert.created_at.desc())
        .limit(_ALERTS_LIMIT)
    ).all()
    return [
        {
            "id": r.id,
            "account_id": r.account_id,
            "phone": r.phone,
            "event_type": f"commenting.{r.kind}",
            "severity": "warning",
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "meta": {
                "campaign_id": r.campaign_id,
                "channel": r.channel_ref,
                "detail": r.detail,
                "channel_alert_id": r.id,
            },
        }
        for r in rows
    ]


def _accounts_summary(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(Account.status, func.count()).group_by(Account.status)
    ).all()
    counts = {status: 0 for status in _ACCOUNT_STATUSES}
    for status, count in rows:
        counts[status] = count
    return counts


def _commenting_summary(session: Session) -> dict[str, Any]:
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    instances = session.execute(
        select(func.count()).select_from(CampaignAccount)
    ).scalar_one()
    active_now = session.execute(
        select(func.count())
        .select_from(CampaignAccount)
        .join(Account, Account.id == CampaignAccount.account_id)
        .where(Account.status == "assigned")
    ).scalar_one()
    today_actions = session.execute(
        select(func.count())
        .select_from(CommentLog)
        .where(CommentLog.created_at >= today_start)
    ).scalar_one()
    return {
        "module": "commenting",
        "instances": instances,
        "active_now": active_now,
        "today_actions": today_actions,
    }


def _recent_activity(session: Session) -> list[dict[str, Any]]:
    warming = select(
        literal("warming").label("type"),
        WarmingActivity.account_id.label("account_id"),
        func.concat(
            WarmingActivity.action_type, literal(" ("), WarmingActivity.status, literal(")")
        ).label("summary"),
        WarmingActivity.created_at.label("ts"),
    )
    comments = select(
        literal("comment").label("type"),
        CommentLog.account_id.label("account_id"),
        func.concat(literal("comment "), CommentLog.status).label("summary"),
        CommentLog.created_at.label("ts"),
    )
    subq = union_all(warming, comments).subquery()
    stmt = select(subq).order_by(subq.c.ts.desc()).limit(_ACTIVITY_LIMIT)
    rows = session.execute(stmt).all()
    return [
        {
            "type": r.type,
            "account_id": r.account_id,
            "summary": r.summary,
            "timestamp": r.ts.isoformat() if r.ts else None,
        }
        for r in rows
    ]


def build_dashboard(session: Session, severity: Optional[str] = None) -> dict[str, Any]:
    """Полный дашборд из БД (без кэша). JSON-safe (timestamps → ISO-строки)."""
    return {
        "alerts": _alerts(session, severity),
        "accounts_summary": _accounts_summary(session),
        "modules_summary": [_commenting_summary(session)],
        "recent_activity": _recent_activity(session),
    }


def get_dashboard(
    session: Session,
    cache: redis.Redis,
    user_id: str,
    severity: Optional[str] = None,
) -> dict[str, Any]:
    """Дашборд с кэшем в Redis (TTL 5с, ключ по user_id).

    Второй запрос в пределах TTL берётся из кэша и в БД не ходит.
    """
    key = _CACHE_KEY.format(user_id=user_id)
    if severity is not None:
        key = f"{key}:sev={severity}"
    cached = cache.get(key)
    if cached is not None:
        if isinstance(cached, (bytes, bytearray)):
            cached = cached.decode()
        return json.loads(cached)

    data = build_dashboard(session, severity)
    cache.setex(key, CACHE_TTL_SECONDS, json.dumps(data, default=str))
    return data
