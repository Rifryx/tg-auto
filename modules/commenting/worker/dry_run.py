"""Сухой прогон кампании нейрокомментинга.

По образцу шиллингового прогона (modules/shilling/worker/dry_run.py): берём текст
тест-поста (введённый вручную или последний пост указанного канала) и для каждого
аккаунта кампании ИИ генерирует комментарий БЕЗ отправки. События публикуются в
Redis-канал ``commenting.dry_run.{job_id}`` — SSE транслирует их в браузер.

Ничего никуда не отправляется: только генерация + оценка риска/бюджета.

Инъекции через ctx: session_factory, publisher, llm_provider, rng, client_pool.
"""

from __future__ import annotations

import random
from typing import Any, Optional

import structlog

from core.repositories.account import AccountRepository
from core.repositories.ban_risk import BanRiskRepository
from modules.commenting.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
)
from modules.commenting.worker import runner
from worker.client_pool import ClientPool
from worker.llm import Message, get_provider

get_logger = structlog.get_logger

# Грубая оценка токенов на один сгенерированный комментарий (prompt + ответ).
_TOKENS_PER_COMMENT = 200
# Сколько аккаунтов максимум показываем в прогоне (чтобы не ждать долго).
_MAX_ACCOUNTS = 6


def dry_run_channel(job_id: str) -> str:
    return f"commenting.dry_run.{job_id}"


def dry_run_req_key(job_id: str) -> str:
    """Redis-ключ с параметрами прогона. SSE забирает его (GETDEL) и ставит
    задачу ПОСЛЕ подписки на канал — иначе события могли бы уйти до подписчика
    (гонка pub/sub, как во фикшеном шиллинге)."""
    return f"commenting.dry_run.{job_id}.req"


def _publish(ctx: dict, channel: str, payload: dict[str, Any]) -> None:
    publisher = ctx.get("publisher")
    if publisher is not None:
        publisher.publish(channel, payload)


def _rng(ctx: dict) -> random.Random:
    return ctx.get("rng") or random.Random()


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


async def _fetch_last_post_text(ctx: dict, account_id: int, channel_ref: str) -> Optional[str]:
    """Последний пост канала через аккаунт (только чтение). None при ошибке."""
    pool = _pool(ctx)
    client = await pool.get(account_id)
    try:
        entity = await client.get_entity(channel_ref)
        messages = await client.get_messages(entity, limit=1)
        if not messages:
            return None
        msg = messages[0]
        return getattr(msg, "message", None) or getattr(msg, "text", None)
    except Exception:  # noqa: BLE001 — не валим прогон, вернём None → попросим текст
        return None
    finally:
        await pool.release(account_id)


async def dry_run(
    ctx: dict,
    campaign_id: int,
    post_text: str,
    channel_ref: str,
    job_id: str,
) -> dict[str, Any]:
    """Симулирует комментарии кампании к тест-посту. Ничего не отправляет."""
    channel = dry_run_channel(job_id)
    session_factory = ctx["session_factory"]
    log = get_logger()

    def _fail(reason: str) -> dict[str, Any]:
        report = {"event": "done", "ok": False, "reason": reason, "job_id": job_id}
        _publish(ctx, channel, report)
        return report

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None:
            return _fail("campaign not found")

        links = CampaignAccountRepository(session).list_by_campaign(campaign_id)
        acc_repo = AccountRepository(session)
        accounts = [a for a in (acc_repo.get(l.account_id) for l in links) if a is not None]
        accounts = accounts[:_MAX_ACCOUNTS]
        if not accounts:
            return _fail("no accounts attached to campaign")
        provider_name = campaign.llm_provider

    text = (post_text or "").strip()
    if not text and channel_ref.strip():
        text = (await _fetch_last_post_text(ctx, accounts[0].id, channel_ref.strip()) or "").strip()
    if not text:
        return _fail("no post text (enter text or a channel to fetch last post)")

    _publish(ctx, channel, {"event": "start", "job_id": job_id, "accounts": len(accounts)})

    provider = ctx.get("llm_provider") or get_provider(provider_name)
    context = [Message(role="user", content=text)]

    total = 0
    worst = "low"
    with session_factory() as session:
        # Свежие ORM-объекты в этой сессии (нужны репозитории внутри _generate).
        campaign = CampaignRepository(session).get(campaign_id)
        risk_repo = BanRiskRepository(session)
        acc_repo = AccountRepository(session)
        for account in (acc_repo.get(a.id) for a in accounts):
            if account is None:
                continue
            try:
                comment, ok = await runner._generate(
                    ctx, session, campaign, account, provider, context
                )
            except Exception as exc:  # noqa: BLE001 — покажем причину, не валим прогон
                comment, ok = f"[ошибка генерации: {type(exc).__name__}]", False
            snap = risk_repo.get(account.id)
            risk = snap.risk_level if snap else "unknown"
            if _rank(risk) > _rank(worst):
                worst = risk
            total += 1
            _publish(
                ctx,
                channel,
                {
                    "event": "step",
                    "account_id": account.id,
                    "account_name": account.username and f"@{account.username}" or account.phone,
                    "text": comment,
                    "ok": ok,
                    "risk_score": risk,
                },
            )

    report = {
        "event": "done",
        "ok": True,
        "job_id": job_id,
        "post_text": text,
        "total_comments": total,
        "worst_risk": worst,
        "estimated_tokens": total * _TOKENS_PER_COMMENT,
    }
    _publish(ctx, channel, report)
    log.info("commenting.dry_run.done", job_id=job_id, campaign_id=campaign_id, total=total)
    return report


def _rank(level: str) -> int:
    return {"low": 0, "medium": 1, "high": 2, "critical": 3, "unknown": 0}.get(level, 0)
