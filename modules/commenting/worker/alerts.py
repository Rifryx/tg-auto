"""Алерты по каналам кампании (E3.2) и автодобавление в чёрный список.

Алерт = строка ``commenting.channel_alerts`` + событие в Redis
``commenting.alerts``. Его ловят: бот-нотифаер (пуш в Telegram) и хаб SSE
дашборда (карточка на главном экране обновляется сразу).

Дедуп: пока есть ОТКРЫТЫЙ алерт с тем же (кампания, аккаунт, канал, вид),
новый не создаётся и повторно не публикуется — иначе каждый пост канала слал
бы тот же пуш заново. Алерт закрывается, когда канал снова заработал.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

get_logger = structlog.get_logger

ALERTS_CHANNEL = "commenting.alerts"


def _model():
    # Лениво: импорт modules.commenting.models на уровне модуля ловит старый
    # цикл core.models <-> modules.commenting.models.
    from modules.commenting.models import ChannelAlert

    return ChannelAlert


def raise_alert(
    session,
    publisher: Any,
    *,
    campaign_id: Optional[int],
    account_id: int,
    channel_ref: str,
    kind: str,
    detail: Optional[str] = None,
) -> Optional[int]:
    """Создаёт алерт (если такого открытого ещё нет), коммитит и публикует.

    Возвращает id нового алерта или None, если сработал дедуп.
    """
    ChannelAlert = _model()
    existing = session.execute(
        select(ChannelAlert.id).where(
            ChannelAlert.campaign_id == campaign_id,
            ChannelAlert.account_id == account_id,
            ChannelAlert.channel_ref == channel_ref,
            ChannelAlert.kind == kind,
            ChannelAlert.resolved.is_(False),
        )
    ).first()
    if existing is not None:
        return None
    alert = ChannelAlert(
        campaign_id=campaign_id,
        account_id=account_id,
        channel_ref=channel_ref,
        kind=kind,
        detail=detail,
    )
    session.add(alert)
    session.commit()
    if publisher is not None:
        publisher.publish(
            ALERTS_CHANNEL,
            {
                "id": alert.id,
                "campaign_id": campaign_id,
                "account_id": account_id,
                "channel": channel_ref,
                "kind": kind,
                "detail": detail,
            },
        )
    get_logger().info(
        "commenting.alert", kind=kind, campaign_id=campaign_id,
        account_id=account_id, channel=channel_ref,
    )
    return alert.id


def resolve_alerts(
    session,
    *,
    account_id: int,
    channel_ref: str,
    kinds: Iterable[str] = ("not_subscribed", "access_lost"),
) -> int:
    """Закрывает открытые алерты по каналу аккаунта (канал снова работает)."""
    ChannelAlert = _model()
    result = session.execute(
        update(ChannelAlert)
        .where(
            ChannelAlert.account_id == account_id,
            ChannelAlert.channel_ref == channel_ref,
            ChannelAlert.kind.in_(tuple(kinds)),
            ChannelAlert.resolved.is_(False),
        )
        .values(resolved=True)
    )
    session.commit()
    return result.rowcount or 0


def auto_blacklist(
    session,
    *,
    campaign_id: int,
    chat_id: Optional[int],
    username: Optional[str],
    reason: str,
) -> bool:
    """Кладёт канал в ЧС кампании (auto=True). False — уже был в ЧС."""
    from modules.commenting.repositories import ChannelBlacklistRepository
    from modules.commenting.schemas import ChannelBlacklistCreate

    repo = ChannelBlacklistRepository(session)
    if repo.find(campaign_id, chat_id=chat_id, username=username) is not None:
        return False
    try:
        repo.create(
            campaign_id,
            ChannelBlacklistCreate(chat_id=chat_id, username=username, reason=reason),
            auto=True,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        return False
    return True
