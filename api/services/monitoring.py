"""Сервис экрана «Главная» (PROJECT-STAGES §10).

Собирает весь дашборд минимумом запросов (агрегаты + один UNION на ленту, без
N+1) и кэширует результат в Redis на 5 секунд по ключу пользователя.

Реестра модулей ещё нет (отложен), поэтому список модулей захардкожен: сейчас
это ``commenting``, ``shilling`` и ``priming``.

Помимо посекундных сводок по модулям дашборд отдаёт верхние KPI-плитки
(``kpis``: действия/ошибки за сегодня, активные и приостановленные кампании,
аккаунты в работе) и 7-дневный ряд действий (``trend_7d``) для спарклайна.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.enums import HealthEventType
from core.models import (
    Account,
    CampaignAccount,
    CommentLog,
    HealthEvent,
    MonitoredChannel,
    ShillingCampaign,
    ShillingExecutionLog,
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


def _alerts(
    session: Session, severity: Optional[str], *, user_id: Optional[str] = None
) -> list[dict[str, Any]]:
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
    # Multi-tenancy: алерты только по своим аккаунтам.
    if user_id is not None:
        stmt = stmt.where(Account.user_id == user_id)
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
        items += _channel_alerts(session, user_id=user_id)
        items.sort(key=lambda a: a["created_at"] or "", reverse=True)
        items = items[:_ALERTS_LIMIT]
    return items


# Открытые алерты целевых каналов нейрокомментинга (E3.2). «Подписали сами»
# на главной не показываем — это не требует действий (уходит только пушем).
_CHANNEL_ALERT_KINDS_ON_DASHBOARD = ("not_subscribed", "access_lost", "blacklisted")


def _channel_alerts(
    session: Session, *, user_id: Optional[str] = None
) -> list[dict[str, Any]]:
    from modules.commenting.models import ChannelAlert

    stmt = (
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
    )
    # Multi-tenancy: алерты каналов только по своим аккаунтам.
    if user_id is not None:
        stmt = stmt.where(Account.user_id == user_id)
    rows = session.execute(
        stmt.order_by(ChannelAlert.created_at.desc()).limit(_ALERTS_LIMIT)
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


def _accounts_summary(
    session: Session, *, user_id: Optional[str] = None
) -> dict[str, int]:
    stmt = select(Account.status, func.count()).group_by(Account.status)
    # Multi-tenancy: считаем только свои аккаунты.
    if user_id is not None:
        stmt = stmt.where(Account.user_id == user_id)
    rows = session.execute(stmt).all()
    counts = {status: 0 for status in _ACCOUNT_STATUSES}
    for status, count in rows:
        counts[status] = count
    return counts


def _commenting_summary(
    session: Session, *, user_id: Optional[str] = None
) -> dict[str, Any]:
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # Multi-tenancy: все три агрегата считаем через join к accounts владельца.
    inst_stmt = select(func.count()).select_from(CampaignAccount)
    active_stmt = (
        select(func.count())
        .select_from(CampaignAccount)
        .join(Account, Account.id == CampaignAccount.account_id)
        .where(Account.status == "assigned")
    )
    today_stmt = (
        select(func.count())
        .select_from(CommentLog)
        .where(CommentLog.created_at >= today_start)
    )
    if user_id is not None:
        inst_stmt = inst_stmt.join(
            Account, Account.id == CampaignAccount.account_id
        ).where(Account.user_id == user_id)
        active_stmt = active_stmt.where(Account.user_id == user_id)
        today_stmt = today_stmt.join(
            Account, Account.id == CommentLog.account_id
        ).where(Account.user_id == user_id)
    instances = session.execute(inst_stmt).scalar_one()
    active_now = session.execute(active_stmt).scalar_one()
    today_actions = session.execute(today_stmt).scalar_one()
    return {
        "module": "commenting",
        "instances": instances,
        "active_now": active_now,
        "today_actions": today_actions,
    }


def _shilling_summary(
    session: Session, *, user_id: Optional[str] = None
) -> dict[str, Any]:
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    inst_stmt = select(func.count()).select_from(ShillingCampaign)
    active_stmt = (
        select(func.count())
        .select_from(ShillingCampaign)
        .where(ShillingCampaign.status == "running")
    )
    today_stmt = (
        select(func.count())
        .select_from(ShillingExecutionLog)
        .where(ShillingExecutionLog.created_at >= today_start)
    )
    # Multi-tenancy: кампании — по владельцу кампании; действия за сегодня —
    # через join к accounts владельца (в логе есть account_id).
    if user_id is not None:
        inst_stmt = inst_stmt.where(ShillingCampaign.owner_user_id == user_id)
        active_stmt = active_stmt.where(ShillingCampaign.owner_user_id == user_id)
        today_stmt = today_stmt.join(
            Account, Account.id == ShillingExecutionLog.account_id
        ).where(Account.user_id == user_id)
    instances = session.execute(inst_stmt).scalar_one()
    active_now = session.execute(active_stmt).scalar_one()
    today_actions = session.execute(today_stmt).scalar_one()
    return {
        "module": "shilling",
        "instances": instances,
        "active_now": active_now,
        "today_actions": today_actions,
    }


def _owner_int(user_id: Optional[str]) -> Optional[int]:
    """created_by у прайминга — BIGINT; user_id из require_user — строка.
    Приводим к int (Telegram id числовой), иначе None."""
    if user_id is None:
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def _priming_summary(
    session: Session, *, user_id: Optional[str] = None
) -> dict[str, Any]:
    from core.models import PrimingCampaign, PrimingExecutionLog

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    owner = _owner_int(user_id)
    inst_stmt = select(func.count()).select_from(PrimingCampaign)
    active_stmt = (
        select(func.count())
        .select_from(PrimingCampaign)
        .where(PrimingCampaign.status == "running")
    )
    today_stmt = (
        select(func.count())
        .select_from(PrimingExecutionLog)
        .where(PrimingExecutionLog.started_at >= today_start)
    )
    # Multi-tenancy: кампании — по владельцу (created_by), действия — через
    # join к accounts владельца (в логе есть account_id).
    if user_id is not None:
        inst_stmt = inst_stmt.where(PrimingCampaign.created_by == owner)
        active_stmt = active_stmt.where(PrimingCampaign.created_by == owner)
        today_stmt = today_stmt.join(
            Account, Account.id == PrimingExecutionLog.account_id
        ).where(Account.user_id == user_id)
    instances = session.execute(inst_stmt).scalar_one()
    active_now = session.execute(active_stmt).scalar_one()
    today_actions = session.execute(today_stmt).scalar_one()
    return {
        "module": "priming",
        "instances": instances,
        "active_now": active_now,
        "today_actions": today_actions,
    }


def _today_start() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _kpis(
    session: Session,
    modules: list[dict[str, Any]],
    *,
    user_id: Optional[str] = None,
) -> dict[str, int]:
    """Сводные числа для верхних плиток: действия сегодня, ошибки сегодня,
    активных кампаний, аккаунтов в работе. Multi-tenancy: всё по своим
    аккаунтам/кампаниям (modules уже отфильтрованы)."""
    from core.models import PrimingCampaign, PrimingExecutionLog

    today = _today_start()
    owner_int = _owner_int(user_id)
    actions_today = sum(int(m.get("today_actions", 0)) for m in modules)
    active_campaigns = sum(int(m.get("active_now", 0)) for m in modules)

    comment_err = (
        select(func.count())
        .select_from(CommentLog)
        .where(CommentLog.created_at >= today, CommentLog.status == "failed")
    )
    shill_err = (
        select(func.count())
        .select_from(ShillingExecutionLog)
        .where(
            ShillingExecutionLog.created_at >= today,
            ShillingExecutionLog.status == "failed",
        )
    )
    acc_working = (
        select(func.count())
        .select_from(Account)
        .where(Account.status.in_(("assigned", "warming")))
    )
    shill_paused = (
        select(func.count())
        .select_from(ShillingCampaign)
        .where(ShillingCampaign.status == "paused")
    )
    prim_paused = (
        select(func.count())
        .select_from(PrimingCampaign)
        .where(PrimingCampaign.status == "paused")
    )
    if user_id is not None:
        comment_err = comment_err.join(
            Account, Account.id == CommentLog.account_id
        ).where(Account.user_id == user_id)
        shill_err = shill_err.join(
            Account, Account.id == ShillingExecutionLog.account_id
        ).where(Account.user_id == user_id)
        acc_working = acc_working.where(Account.user_id == user_id)
        shill_paused = shill_paused.where(ShillingCampaign.owner_user_id == user_id)
        prim_paused = prim_paused.where(PrimingCampaign.created_by == owner_int)

    errors_today = 0
    errors_today += session.execute(comment_err).scalar_one()
    errors_today += session.execute(shill_err).scalar_one()
    accounts_working = session.execute(acc_working).scalar_one()
    # Кампании «на паузе» всех модулей — чтобы было видно, что требует внимания.
    paused_campaigns = session.execute(shill_paused).scalar_one()
    paused_campaigns += session.execute(prim_paused).scalar_one()

    return {
        "actions_today": int(actions_today),
        "errors_today": int(errors_today),
        "active_campaigns": int(active_campaigns),
        "paused_campaigns": int(paused_campaigns),
        "accounts_working": int(accounts_working),
    }


def _trend_7d(
    session: Session, *, user_id: Optional[str] = None
) -> list[dict[str, Any]]:
    """Действия по дням за последние 7 суток (UTC). Склеиваем три источника —
    комментарии, шиллинг и прайминг — в один дневной ряд для спарклайна.
    Multi-tenancy: каждый источник — только по аккаунтам владельца (join)."""
    from core.models import PrimingExecutionLog

    start = _today_start() - timedelta(days=6)
    counts: dict[str, int] = {}

    def _bucket(col, account_col) -> None:
        stmt = select(func.date(col), func.count()).where(col >= start)
        if user_id is not None:
            stmt = stmt.join(Account, Account.id == account_col).where(
                Account.user_id == user_id
            )
        stmt = stmt.group_by(func.date(col))
        for day, cnt in session.execute(stmt).all():
            counts[str(day)] = counts.get(str(day), 0) + int(cnt)

    _bucket(CommentLog.created_at, CommentLog.account_id)
    _bucket(ShillingExecutionLog.created_at, ShillingExecutionLog.account_id)
    _bucket(PrimingExecutionLog.started_at, PrimingExecutionLog.account_id)

    out: list[dict[str, Any]] = []
    for i in range(7):
        day = (start + timedelta(days=i)).date()
        out.append({"date": day.isoformat(), "actions": counts.get(day.isoformat(), 0)})
    return out


def _recent_activity(
    session: Session, *, user_id: Optional[str] = None
) -> list[dict[str, Any]]:
    from core.warming_detail import warming_detail

    # Две отдельные выборки (без union по разнотипным колонкам) → мёрдж в Python.
    warming_stmt = select(
        WarmingActivity.account_id,
        WarmingActivity.action_type,
        WarmingActivity.target,
        WarmingActivity.meta,
        WarmingActivity.status,
        WarmingActivity.created_at,
    )
    comment_stmt = select(
        CommentLog.account_id,
        CommentLog.status,
        CommentLog.created_at,
        CommentLog.channel_ref,
    )
    # Multi-tenancy: лента активности — только по своим аккаунтам.
    if user_id is not None:
        warming_stmt = warming_stmt.join(
            Account, Account.id == WarmingActivity.account_id
        ).where(Account.user_id == user_id)
        comment_stmt = comment_stmt.join(
            Account, Account.id == CommentLog.account_id
        ).where(Account.user_id == user_id)
    warming_rows = session.execute(
        warming_stmt.order_by(WarmingActivity.created_at.desc()).limit(_ACTIVITY_LIMIT)
    ).all()
    comment_rows = session.execute(
        comment_stmt.order_by(CommentLog.created_at.desc()).limit(_ACTIVITY_LIMIT)
    ).all()

    events: list[dict[str, Any]] = []
    for r in warming_rows:
        events.append(
            {
                "type": "warming",
                "account_id": r.account_id,
                "action_type": r.action_type,
                "summary": f"{r.action_type} ({r.status})",
                "detail": warming_detail(
                    r.action_type, target=r.target, meta=r.meta, status=r.status
                ),
                "status": r.status,
                "ts": r.created_at,
            }
        )
    for r in comment_rows:
        events.append(
            {
                "type": "comment",
                "account_id": r.account_id,
                "action_type": "comment",
                "summary": f"comment {r.status}",
                "detail": f"комментарий ({r.status})",
                "status": r.status,
                "ts": r.created_at,
                # Реальный канал поста из лога (а не «первый канал аккаунта»).
                "channel_ref": r.channel_ref,
            }
        )

    events.sort(key=lambda e: e["ts"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    events = events[:_ACTIVITY_LIMIT]

    # Подпись аккаунта (номер + своё имя) — чтобы в аудите было видно, какого
    # аккаунта касается событие. Одним запросом по уникальным id (без N+1).
    acc_ids = {e["account_id"] for e in events if e["account_id"] is not None}
    labels: dict[int, tuple[Optional[str], Optional[str]]] = {}
    if acc_ids:
        for aid, phone, display_name in session.execute(
            select(Account.id, Account.phone, Account.display_name).where(
                Account.id.in_(acc_ids)
            )
        ).all():
            labels[aid] = (phone, display_name)

    # Канал для событий-комментариев берём из САМОГО лога (CommentLog.channel_ref)
    # — это реальный канал поста. Раньше канал определялся «первым каналом
    # аккаунта», и для аккаунтов с несколькими каналами подпись была неверной
    # (баг-репорт: «пишет коммент в канал X, а по факту писалось в Y»).
    # Фолбэк по первому каналу аккаунта — только для СТАРЫХ логов без channel_ref
    # и только если у аккаунта ровно один канал (иначе не угадываем — не
    # показываем канал вовсе, лучше без подписи, чем неверная).
    legacy_acc_ids = {
        e["account_id"] for e in events
        if e["type"] == "comment"
        and e["account_id"] is not None
        and not (e.get("channel_ref") or "").strip()
    }
    channel_by_acc: dict[int, Optional[str]] = {}
    if legacy_acc_ids:
        counts: dict[int, int] = {}
        first_name: dict[int, str] = {}
        for acc_id, title, ref in session.execute(
            select(
                MonitoredChannel.account_id,
                MonitoredChannel.title,
                MonitoredChannel.channel_ref,
            )
            .where(MonitoredChannel.account_id.in_(legacy_acc_ids))
            .order_by(MonitoredChannel.account_id, MonitoredChannel.id)
        ).all():
            counts[acc_id] = counts.get(acc_id, 0) + 1
            if acc_id not in first_name:
                name = (title or ref or "").strip()
                if name:
                    first_name[acc_id] = name
        # Подставляем только когда канал ровно один (однозначно).
        for acc_id, cnt in counts.items():
            if cnt == 1 and acc_id in first_name:
                channel_by_acc[acc_id] = first_name[acc_id]

    result: list[dict[str, Any]] = []
    for e in events:
        channel = None
        if e["type"] == "comment":
            channel = (e.get("channel_ref") or "").strip() or channel_by_acc.get(
                e["account_id"]
            )
        detail = e["detail"]
        if channel:
            detail = f"{detail} → {channel}"
        result.append(
            {
                "type": e["type"],
                "account_id": e["account_id"],
                "phone": labels.get(e["account_id"], (None, None))[0],
                "display_name": labels.get(e["account_id"], (None, None))[1],
                "action_type": e["action_type"],
                "summary": e["summary"],
                "detail": detail,
                "channel": channel,
                "status": e["status"],
                "timestamp": e["ts"].isoformat() if e["ts"] else None,
            }
        )
    return result


def build_dashboard(
    session: Session,
    severity: Optional[str] = None,
    *,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Полный дашборд из БД (без кэша). JSON-safe (timestamps → ISO-строки).

    ``user_id`` (multi-tenancy): когда задан, все агрегаты/лента/алерты/KPI/
    тренд фильтруются по аккаунтам и кампаниям владельца. None — весь срез
    (тесты)."""
    modules = [
        _commenting_summary(session, user_id=user_id),
        _shilling_summary(session, user_id=user_id),
        _priming_summary(session, user_id=user_id),
    ]
    return {
        "alerts": _alerts(session, severity, user_id=user_id),
        "accounts_summary": _accounts_summary(session, user_id=user_id),
        "modules_summary": modules,
        "kpis": _kpis(session, modules, user_id=user_id),
        "trend_7d": _trend_7d(session, user_id=user_id),
        "recent_activity": _recent_activity(session, user_id=user_id),
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

    data = build_dashboard(session, severity, user_id=user_id)
    cache.setex(key, CACHE_TTL_SECONDS, json.dumps(data, default=str))
    return data
