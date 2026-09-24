"""Verify-after-post: тем же аккаунтом, что постил, проверяем через
verify_delay_sec, что коммент всё ещё виден в обсуждении (E4.2).

Правило who-comments (MEMORY: monitoring-architecture): смотрит именно
аккаунт-автор коммента. Другой аккаунт даже с тем же ban_risk увидел бы
другую реальность (мьют, автомодератор). Плюс это не тратит лишний
клиент.

Событие:
* коммент найден  → verified_at=now, публикуем ``commenting.verify.ok``;
* коммент None    → status='flagged', error='removed_by_moderator',
                    removed_at=now, публикуем алерт
                    ``commenting.alerts`` (kind='comment_removed');
* аккаунт больше не пригоден (retired/banned/cooldown) → скипаем.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from core.enums import CommentStatus
from core.models import Account, CommentLog
from worker.client_pool import ClientPool
from worker.health import around_telethon_call

get_logger = structlog.get_logger

VERIFY_OK_CHANNEL = "commenting.verify.ok"
VERIFY_REMOVED_CHANNEL = "commenting.alerts"

# Аккаунты в этих статусах не трогаем: pool/warming/cooldown/banned/retired
# — их клиенты либо нельзя подключить, либо это может вернуть их в live-режим
# в неудобный момент. Пропускаем — статистика покажет неверифицированный лог.
_ELIGIBLE_STATUSES = {"assigned", "pool"}


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


def _now(ctx: dict) -> datetime:
    return ctx.get("now") or datetime.now(timezone.utc)


def _discussion_group(session, log: CommentLog) -> int | None:
    """discussion-group коммента: сначала пробуем канал-центричную кампанию
    (campaigns.discussion_group_id), иначе — MonitoredChannel аккаунта."""
    from modules.commenting.repositories import (
        CampaignRepository,
        MonitoredChannelRepository,
    )

    campaign = CampaignRepository(session).get(log.campaign_id)
    if campaign is not None and campaign.discussion_group_id is not None:
        return campaign.discussion_group_id
    # Аккаунт-центричный путь: обсуждение живёт в MonitoredChannel аккаунта.
    for row in MonitoredChannelRepository(session).list_working_by_account(log.account_id):
        if row.discussion_group_id is not None:
            return row.discussion_group_id
    return None


def _publish(publisher: Any, channel: str, payload: dict) -> None:
    if publisher is None:
        return
    try:
        publisher.publish(channel, payload)
    except Exception as exc:  # noqa: BLE001
        get_logger().warning("commenting.verify.publish_failed", channel=channel, error=repr(exc))


async def verify_comment(ctx: dict, comment_log_id: int) -> str:
    """Проверяет, что коммент всё ещё виден. Возвращает 'ok'/'removed'/'skipped'."""
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    now = _now(ctx)
    log = get_logger()

    with session_factory() as session:
        row = session.get(CommentLog, comment_log_id)
        if row is None or row.status != CommentStatus.POSTED.value or row.posted_message_id is None:
            return "skipped"
        if row.verified_at is not None or row.removed_at is not None:
            # Повтор задачи не должен дважды писать в лог/алерт.
            return "skipped"
        account = session.get(Account, row.account_id)
        if account is None or account.status not in _ELIGIBLE_STATUSES:
            log.info(
                "commenting.verify.skip",
                account_id=row.account_id, reason="account_ineligible",
                status=getattr(account, "status", None),
            )
            return "skipped"
        discussion_group_id = _discussion_group(session, row)
        if discussion_group_id is None:
            log.info("commenting.verify.skip", comment_log_id=comment_log_id, reason="no_group")
            return "skipped"
        posted_id = row.posted_message_id
        campaign_id = row.campaign_id
        account_id = row.account_id

    pool = _pool(ctx)
    client = await pool.get(account_id)
    found = None
    try:
        messages = await around_telethon_call(
            lambda: client.get_messages(discussion_group_id, ids=[posted_id]),
            account_id=account_id,
            session_factory=session_factory,
            publisher=publisher,
            now=now,
        )
        if isinstance(messages, (list, tuple)):
            found = messages[0] if messages else None
        else:
            found = messages
    except Exception as exc:  # noqa: BLE001
        # Ошибка сети/доступа — не пишем «удалено», пропускаем. Пусть
        # следующий (плановый) запуск попробует ещё раз, или пользователь
        # разберётся руками.
        log.warning(
            "commenting.verify.error",
            comment_log_id=comment_log_id, error=repr(exc),
        )
        return "skipped"
    finally:
        await pool.release(account_id)

    with session_factory() as session:
        row = session.get(CommentLog, comment_log_id)
        if row is None:
            return "skipped"
        if found is None:
            row.status = CommentStatus.FLAGGED.value
            row.error = "removed_by_moderator"
            row.removed_at = now
            session.commit()
            _publish(
                publisher, VERIFY_REMOVED_CHANNEL,
                {
                    "kind": "comment_removed",
                    "comment_log_id": comment_log_id,
                    "campaign_id": campaign_id,
                    "account_id": account_id,
                    "posted_message_id": posted_id,
                },
            )
            log.info(
                "commenting.verify.removed",
                comment_log_id=comment_log_id, account_id=account_id,
                campaign_id=campaign_id,
            )
            return "removed"
        row.verified_at = now
        session.commit()
    _publish(
        publisher, VERIFY_OK_CHANNEL,
        {"comment_log_id": comment_log_id, "campaign_id": campaign_id, "account_id": account_id},
    )
    log.info(
        "commenting.verify.ok",
        comment_log_id=comment_log_id, account_id=account_id, campaign_id=campaign_id,
    )
    return "ok"
