"""Сухой прогон кампании шиллинга (docs/neuroshilling-spec.md § 4.5, ui-ux § 5.6).

Проигрывает сценарий на тестовом чате БЕЗ реальной отправки: генерирует текст
(с уникализацией, если включена), считает тайминги, риск и расход токенов, и
публикует события в Redis-канал ``shilling.dry_run.{job_id}`` — SSE-эндпоинт
транслирует их в браузер в реальном времени.

Инъекции через ctx: session_factory, now, rng, client_pool, publisher,
llm_provider.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

import structlog

from core.repositories.ban_risk import BanRiskRepository
from modules.shilling.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    ScenarioRepository,
    ScenarioRoleRepository,
    ScenarioStepRepository,
)
from modules.shilling.schemas import DryRunReport, DryRunStep
from modules.shilling.worker.orchestrator import _resolve_discussion_root, _validate_ready
from worker.client_pool import ClientPool

get_logger = structlog.get_logger

# Грубая оценка расхода токенов на одну реплику (rewrite): prompt + ответ.
_TOKENS_PER_STEP = 200


def dry_run_channel(job_id: str) -> str:
    return f"shilling.dry_run.{job_id}"


def _now(ctx: dict) -> datetime:
    return ctx.get("now") or datetime.now(timezone.utc)


def _rng(ctx: dict) -> random.Random:
    return ctx.get("rng") or random.Random()


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


def _publish(ctx: dict, channel: str, payload: dict[str, Any]) -> None:
    publisher = ctx.get("publisher")
    if publisher is not None:
        publisher.publish(channel, payload)


async def dry_run(
    ctx: dict,
    campaign_id: int,
    test_target: str,
    job_id: str,
) -> DryRunReport:
    """Симулирует прогон сценария на ``test_target``. Ничего не отправляет."""
    channel = dry_run_channel(job_id)
    now = _now(ctx)
    rng = _rng(ctx)
    session_factory = ctx["session_factory"]
    publisher_now = now
    log = get_logger()

    def _fail(reason: str) -> DryRunReport:
        report = DryRunReport(job_id=job_id, ok=False, reason=reason)
        _publish(ctx, channel, {"event": "done", **report.model_dump()})
        return report

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None:
            return _fail("campaign not found")
        ok, reason = _validate_ready(session, campaign)
        if not ok:
            return _fail(f"not ready: {reason}")

        scenario = ScenarioRepository(session).get_by_campaign(campaign_id)
        steps = ScenarioStepRepository(session).list_by_scenario(scenario.id)
        steps = [s for s in steps if s.step_type in ("message", "reaction")]

        link_repo = CampaignAccountRepository(session)
        role_repo = ScenarioRoleRepository(session)
        risk_repo = BanRiskRepository(session)

        unique = campaign.unique_messages
        brand = campaign.brand_name
        provider_name = campaign.llm_provider
        reply_lo, reply_hi = campaign.reply_delay_min_sec, campaign.reply_delay_max_sec

        # Собираем «сырой» план внутри сессии (нужны поля step/role/account).
        raw_plan = []
        for step in steps:
            primaries = link_repo.list_primary_by_role(campaign_id, step.role_id)
            if not primaries:
                continue
            account_id = rng.choice(primaries).account_id
            role = role_repo.get(step.role_id)
            snap = risk_repo.get(account_id)
            raw_plan.append(
                {
                    "step_id": step.id,
                    "step_type": step.step_type,
                    "account_id": account_id,
                    "role_name": role.name if role else "",
                    "role_character": role.character if role else None,
                    "base_text": step.text or "",
                    "reaction_emoji": step.reaction_emoji,
                    "delay": step.delay_before_sec,
                    "risk_score": snap.risk_level if snap else "unknown",
                }
            )

    if not raw_plan:
        return _fail("no executable steps (no accounts for roles?)")

    _publish(ctx, channel, {"event": "start", "job_id": job_id, "steps": len(raw_plan)})

    # Резолвим тестовый чат — только проверка доступа (без постинга).
    resolver_account_id = raw_plan[0]["account_id"]
    pool = _pool(ctx)
    client = await pool.get(resolver_account_id)
    try:
        discussion_group_id, _root = await _resolve_discussion_root(
            client, test_target,
            account_id=resolver_account_id, session_factory=session_factory,
            publisher=ctx.get("publisher"), now=publisher_now,
        )
    except Exception as exc:  # noqa: BLE001
        await pool.release(resolver_account_id)
        return _fail(f"test target resolve failed: {type(exc).__name__}")
    finally:
        await pool.release(resolver_account_id)

    if discussion_group_id is None:
        return _fail("test target has no open comments / discussion group")

    # Симуляция шагов.
    timeline: list[DryRunStep] = []
    cumulative = 0
    total_messages = total_reactions = 0
    for item in raw_plan:
        delay = item["delay"]
        if delay is None:
            delay = int(rng.uniform(reply_lo, reply_hi))
        cumulative += int(delay)

        if item["step_type"] == "reaction":
            total_reactions += 1
            text = f"[реакция] {item['reaction_emoji'] or ''}".strip()
        else:
            total_messages += 1
            text = item["base_text"]
            if unique and text:
                provider = ctx.get("llm_provider")
                if provider is None:
                    from worker.llm import get_provider

                    provider = get_provider(provider_name)
                from modules.shilling.llm import ReplicaRewriter

                text = await ReplicaRewriter(provider).rewrite(
                    item["base_text"],
                    role_name=item["role_name"],
                    role_character=item["role_character"],
                    brand_name=brand,
                )

        entry = DryRunStep(
            step_id=item["step_id"],
            account_id=item["account_id"],
            role_name=item["role_name"],
            text=text,
            scheduled_at_sec=cumulative,
            risk_score=item["risk_score"],
        )
        timeline.append(entry)
        _publish(ctx, channel, {"event": "step", **entry.model_dump()})

    report = DryRunReport(
        job_id=job_id,
        ok=True,
        timeline=timeline,
        total_messages=total_messages,
        total_reactions=total_reactions,
        duration_sec=cumulative,
        estimated_tokens=total_messages * _TOKENS_PER_STEP if unique else 0,
    )
    _publish(ctx, channel, {"event": "done", **report.model_dump()})
    log.info(
        "shilling.dry_run.done",
        job_id=job_id, campaign_id=campaign_id, steps=len(timeline),
        duration_sec=cumulative,
    )
    return report
