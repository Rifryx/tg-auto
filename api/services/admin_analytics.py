"""Сводная аналитика сервиса для админки (``GET /admin/analytics``).

Всё считается прямыми агрегатами по БД — точно и без кэша. Объём данных MVP
небольшой, запросы индексированы (status/created_at), так что дешевле держать
правду в БД, чем заводить отдельные счётчики.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models.account import Account
from core.models.bulk_job import BulkJob
from core.models.payment import Payment
from core.models.persona import Persona
from core.models.proxy import Proxy
from core.models.subscription import Subscription
from core.models.priming import PrimingCampaign
from modules.commenting.models.campaign import Campaign
from modules.commenting.models.comment_log import CommentLog
from modules.shilling.models import ShillingCampaign


def _count(session: Session, model, *where) -> int:
    stmt = select(func.count()).select_from(model)
    for cond in where:
        stmt = stmt.where(cond)
    return int(session.execute(stmt).scalar_one())


def _users_block(session: Session, now: datetime) -> dict[str, object]:
    total = _count(session, Subscription)
    pro_active = _count(
        session,
        Subscription,
        Subscription.plan_id == "pro",
        (Subscription.expires_at.is_(None)) | (Subscription.expires_at > now),
    )
    new_7d = _count(session, Subscription, Subscription.activated_at >= now - timedelta(days=7))
    new_30d = _count(session, Subscription, Subscription.activated_at >= now - timedelta(days=30))
    expiring_7d = _count(
        session,
        Subscription,
        Subscription.plan_id == "pro",
        Subscription.expires_at.is_not(None),
        Subscription.expires_at > now,
        Subscription.expires_at <= now + timedelta(days=7),
    )
    return {
        "total": total,
        "pro_active": pro_active,
        "free": max(total - pro_active, 0),
        "new_7d": new_7d,
        "new_30d": new_30d,
        "expiring_7d": expiring_7d,
        "conversion_pct": round(100 * pro_active / total, 1) if total else 0.0,
    }


def _revenue_block(session: Session, now: datetime) -> dict[str, object]:
    rows = session.execute(
        select(
            Payment.provider,
            Payment.currency,
            func.count(),
            func.coalesce(func.sum(Payment.amount), 0),
        )
        .where(Payment.status == "paid")
        .group_by(Payment.provider, Payment.currency)
    ).all()
    by_currency = [
        {
            "provider": provider,
            "currency": currency,
            "count": int(cnt),
            "total": float(total),
        }
        for provider, currency, cnt, total in rows
    ]
    paid_30d = _count(
        session,
        Payment,
        Payment.status == "paid",
        Payment.paid_at >= now - timedelta(days=30),
    )
    return {
        "by_currency": by_currency,
        "paid_total": _count(session, Payment, Payment.status == "paid"),
        "paid_30d": paid_30d,
        "pending": _count(session, Payment, Payment.status == "pending"),
    }


def _accounts_by_status(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(Account.status, func.count()).group_by(Account.status)
    ).all()
    return {status: int(cnt) for status, cnt in rows}


def _activity_block(session: Session, now: datetime) -> dict[str, object]:
    comments_24h = _count(
        session,
        CommentLog,
        CommentLog.status == "posted",
        CommentLog.created_at >= now - timedelta(hours=24),
    )
    comments_7d = _count(
        session,
        CommentLog,
        CommentLog.status == "posted",
        CommentLog.created_at >= now - timedelta(days=7),
    )
    return {
        "comments_24h": comments_24h,
        "comments_7d": comments_7d,
        "accounts_by_status": _accounts_by_status(session),
        "campaigns": {
            "commenting": _count(session, Campaign),
            "shilling": _count(session, ShillingCampaign),
            "priming": _count(session, PrimingCampaign),
        },
    }


def _load_block(session: Session) -> dict[str, object]:
    return {
        "bulk_jobs_queued": _count(session, BulkJob, BulkJob.status == "queued"),
        "bulk_jobs_running": _count(session, BulkJob, BulkJob.status == "running"),
        "accounts_total": _count(session, Account),
        "accounts_working": _count(
            session,
            Account,
            Account.status.in_(("warming", "pool", "assigned")),
        ),
        "personas": _count(session, Persona),
        "proxies": _count(session, Proxy),
    }


def get_analytics(session: Session) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "generated_at": now.isoformat(),
        "users": _users_block(session, now),
        "revenue": _revenue_block(session, now),
        "activity": _activity_block(session, now),
        "load": _load_block(session),
    }
