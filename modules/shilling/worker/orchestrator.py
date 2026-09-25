"""Оркестратор кампании шиллинга (docs/neuroshilling-spec.md § 5.2, 5.3).

Пока реализован ``failover`` (промпт 4.3) — замена забаненного аккаунта на
резервный той же роли. ``start_campaign`` / ``process_target`` — промпт 4.4.

Инъекции через ctx: session_factory, task_queue, now, rng, publisher.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

from core.queue import TaskQueue
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from modules.shilling.repositories import (
    BlacklistRepository,
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
    ExecutionLogRepository,
    ScenarioRepository,
    ScenarioStepRepository,
)
from modules.shilling.schemas import BlacklistCreate
from worker.client_pool import ClientPool

get_logger = structlog.get_logger

_USABLE_ACCOUNT_STATUSES = {"pool", "assigned"}


def _now(ctx: dict) -> datetime:
    return ctx.get("now") or datetime.now(timezone.utc)


def _rng(ctx: dict) -> random.Random:
    return ctx.get("rng") or random.Random()


def _task_queue(ctx: dict) -> TaskQueue:
    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


def _pool(ctx: dict) -> ClientPool:
    pool = ctx.get("client_pool")
    if pool is None:
        pool = ClientPool(ctx["session_factory"])
        ctx["client_pool"] = pool
    return pool


# --- задача start_campaign ---------------------------------------------------


async def start_campaign(ctx: dict, campaign_id: int) -> int:
    """Валидирует кампанию и раскидывает цели по очереди с кулдауном.

    Возвращает число запланированных целей. При провале валидации переводит
    кампанию в status='error' и возвращает 0.
    """
    now = _now(ctx)
    rng = _rng(ctx)
    session_factory = ctx["session_factory"]
    task_queue = _task_queue(ctx)
    log = get_logger()

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None:
            log.info("shilling.start.skip", campaign_id=campaign_id, reason="no_campaign")
            return 0
        if not campaign.enabled or campaign.status != "running":
            log.info("shilling.start.skip", campaign_id=campaign_id, reason="not_running")
            return 0

        ok, reason = _validate_ready(session, campaign)
        if not ok:
            CampaignRepository(session).set_status(campaign_id, "error")
            session.commit()
            log.warning("shilling.start.not_ready", campaign_id=campaign_id, reason=reason)
            return 0

        targets = CampaignTargetRepository(session).list_by_campaign(campaign_id)
        delay_lo = campaign.target_delay_min_sec
        delay_hi = campaign.target_delay_max_sec
        target_ids = [t.id for t in targets]

    # Планируем цели последовательно: кулдаун накапливается между целями.
    cumulative = 0.0
    for target_id in target_ids:
        run_at = now + timedelta(seconds=cumulative)
        await task_queue.schedule(
            TaskName.SHILLING_PROCESS_TARGET, run_at, campaign_id, target_id
        )
        cumulative += rng.uniform(delay_lo, delay_hi)

    log.info("shilling.start.scheduled", campaign_id=campaign_id, targets=len(target_ids))
    return len(target_ids)


def _validate_ready(session, campaign) -> tuple[bool, str]:
    """Минимальная проверка готовности (аналог API readiness, но без схем)."""
    scenario = ScenarioRepository(session).get_by_campaign(campaign.id)
    if scenario is None:
        return False, "no_scenario"
    steps = ScenarioStepRepository(session).list_by_scenario(scenario.id)
    if not any(s.step_type == "message" for s in steps):
        return False, "no_message_steps"
    links = CampaignAccountRepository(session).list_by_campaign(campaign.id)
    primary = [link for link in links if not link.is_reserve]
    if len(primary) < scenario.persons_count:
        return False, "not_enough_accounts"
    if not CampaignTargetRepository(session).list_by_campaign(campaign.id):
        return False, "no_targets"
    return True, ""


# --- задача process_target ---------------------------------------------------


async def process_target(ctx: dict, campaign_id: int, target_id: int) -> int:
    """Готовит цель (резолв + корень обсуждения) и планирует шаги сценария.

    Возвращает число запланированных шагов (0 — если цель пропущена).
    """
    now = _now(ctx)
    rng = _rng(ctx)
    session_factory = ctx["session_factory"]
    publisher = ctx.get("publisher")
    task_queue = _task_queue(ctx)
    log = get_logger()

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None or not campaign.enabled or campaign.status != "running":
            log.info("shilling.process_target.skip", campaign_id=campaign_id, reason="not_running")
            return 0

        target = CampaignTargetRepository(session).get(target_id)
        if target is None or target.campaign_id != campaign_id:
            log.info("shilling.process_target.skip", target_id=target_id, reason="no_target")
            return 0

        # Чёрный список (по chat_id или username).
        username = target.raw_input if target.kind == "username" else None
        if BlacklistRepository(session).is_blacklisted(
            campaign_id, chat_id=target.resolved_chat_id, username=username
        ):
            log.info("shilling.process_target.skip", target_id=target_id, reason="blacklisted")
            return 0

        scenario = ScenarioRepository(session).get_by_campaign(campaign_id)
        if scenario is None:
            return 0
        steps = ScenarioStepRepository(session).list_by_scenario(scenario.id)
        message_or_reaction = [s for s in steps if s.step_type in ("message", "reaction")]
        if not message_or_reaction:
            return 0

        raw_ref = target.resolved_chat_id or target.raw_input
        reply_lo = campaign.reply_delay_min_sec
        reply_hi = campaign.reply_delay_max_sec
        # Заранее подбираем аккаунт на каждый шаг (primary по роли).
        link_repo = CampaignAccountRepository(session)
        plan: list[tuple[int, Optional[int], Optional[int]]] = []  # (step_id, account_id, delay)
        for step in message_or_reaction:
            primaries = link_repo.list_primary_by_role(campaign_id, step.role_id)
            if not primaries:
                log.info(
                    "shilling.process_target.step_skip",
                    step_id=step.id, reason="no_account_for_role",
                )
                continue
            account_id = rng.choice(primaries).account_id
            delay = step.delay_before_sec
            if delay is None:
                delay = rng.uniform(reply_lo, reply_hi)
            plan.append((step.id, account_id, delay))

        # Аккаунт для резолва канала — любой primary.
        resolver_links = [l for l in link_repo.list_by_campaign(campaign_id) if not l.is_reserve]
        resolver_account_id = resolver_links[0].account_id if resolver_links else None

    if not plan or resolver_account_id is None:
        log.info("shilling.process_target.skip", target_id=target_id, reason="empty_plan")
        return 0

    # Резолвим канал + находим корневое сообщение обсуждения.
    pool = _pool(ctx)
    client = await pool.get(resolver_account_id)
    try:
        discussion_group_id, root_msg_id = await _resolve_discussion_root(
            client, raw_ref,
            account_id=resolver_account_id, session_factory=session_factory,
            publisher=publisher, now=now,
        )
    except Exception as exc:  # noqa: BLE001 — резолв упал → цель в ЧС
        await pool.release(resolver_account_id)
        with session_factory() as session:
            CampaignTargetRepository(session).mark_error(target_id, type(exc).__name__)
            _blacklist_target(session, campaign_id, target_id, reason=f"resolve failed: {type(exc).__name__}")
            session.commit()
        log.warning("shilling.process_target.resolve_failed", target_id=target_id, error=type(exc).__name__)
        return 0
    finally:
        await pool.release(resolver_account_id)

    if discussion_group_id is None:
        with session_factory() as session:
            CampaignTargetRepository(session).mark_error(target_id, "no_discussion_group")
            _blacklist_target(session, campaign_id, target_id, reason="comments closed / no discussion")
            session.commit()
        log.info("shilling.process_target.skip", target_id=target_id, reason="no_discussion")
        return 0

    # Целевой чат для постинга — discussion-группа (executor шлёт в resolved_chat_id).
    with session_factory() as session:
        CampaignTargetRepository(session).mark_resolved(
            target_id, resolved_chat_id=discussion_group_id
        )
        session.commit()

    # Планируем шаги с накопительной задержкой; все reply к корню обсуждения.
    cumulative = 0.0
    for step_id, account_id, delay in plan:
        cumulative += float(delay)
        run_at = now + timedelta(seconds=cumulative)
        await task_queue.schedule(
            TaskName.SHILLING_EXECUTE_STEP,
            run_at,
            campaign_id,
            target_id,
            step_id,
            account_id,
            thread_msg_id=root_msg_id,
        )
    log.info(
        "shilling.process_target.scheduled",
        target_id=target_id, steps=len(plan), discussion_group_id=discussion_group_id,
    )
    return len(plan)


async def _resolve_discussion_root(
    client: Any,
    raw_ref,
    *,
    account_id: int,
    session_factory,
    publisher,
    now,
) -> tuple[Optional[int], Optional[int]]:
    """Возвращает (discussion_group_id, root_msg_id) для последнего поста канала.

    root_msg_id — id корневого сообщения в linked-группе, к которому реплаятся
    комментарии. None-группа означает, что обсуждения нет (комментарии закрыты).
    """
    from telethon.tl.functions.channels import GetFullChannelRequest
    from telethon.tl.functions.messages import GetDiscussionMessageRequest
    from worker.health import around_telethon_call

    async def _call(factory):
        return await around_telethon_call(
            factory, account_id=account_id, session_factory=session_factory,
            publisher=publisher, now=now,
        )

    entity = await _call(lambda: client.get_entity(raw_ref))
    full = await _call(lambda: client(GetFullChannelRequest(entity)))
    linked = getattr(getattr(full, "full_chat", None), "linked_chat_id", None)
    if linked is None:
        return None, None

    posts = await _call(lambda: client.get_messages(entity, limit=1))
    if not posts:
        return linked, None
    post_id = getattr(posts[0], "id", None)
    if post_id is None:
        return linked, None

    disc = await _call(
        lambda: client(GetDiscussionMessageRequest(peer=entity, msg_id=post_id))
    )
    disc_messages = getattr(disc, "messages", None) or []
    root_msg_id = getattr(disc_messages[0], "id", None) if disc_messages else None
    return linked, root_msg_id


# --- задача failover ---------------------------------------------------------


async def failover(
    ctx: dict,
    campaign_id: int,
    target_id: int,
    step_id: int,
    failed_account_id: int,
    thread_msg_id: Optional[int] = None,
) -> Optional[int]:
    """Заменяет забаненный аккаунт резервным той же роли и продолжает шаг.

    Возвращает id нового аккаунта, если замена произошла, иначе None.
    Если резерв исчерпан (или выключен) — цель уходит в ЧС (auto=True).
    """
    session_factory = ctx["session_factory"]
    task_queue = _task_queue(ctx)
    log = get_logger()

    with session_factory() as session:
        campaign = CampaignRepository(session).get(campaign_id)
        if campaign is None or not campaign.enabled or campaign.status != "running":
            log.info("shilling.failover.skip", campaign_id=campaign_id, reason="not_running")
            return None

        link_repo = CampaignAccountRepository(session)
        failed_link = link_repo.get_link(campaign_id, failed_account_id)
        role_id = failed_link.role_id if failed_link else None

        # Реролл запрещён без включённого резерва → сразу в ЧС.
        if not campaign.reserve_enabled:
            _blacklist_target(session, campaign_id, target_id, reason="reserve disabled")
            session.commit()
            log.warning("shilling.failover.reserve_disabled", campaign_id=campaign_id)
            return None

        # Аккаунты, уже провалившиеся на этой цели — не пробуем повторно.
        failed_ids = {
            entry.account_id
            for entry in ExecutionLogRepository(session).list_failed_for_target(
                campaign_id, target_id
            )
        }
        failed_ids.add(failed_account_id)

        acc_repo = AccountRepository(session)
        chosen = None
        for reserve in link_repo.list_reserve(campaign_id):
            if reserve.account_id in failed_ids:
                continue
            # Резерв без роли (None) можно поставить на любую; иначе роль должна
            # совпадать с ролью выбывшего аккаунта.
            if reserve.role_id not in (None, role_id):
                continue
            acc = acc_repo.get(reserve.account_id)
            if acc is None or acc.status not in _USABLE_ACCOUNT_STATUSES:
                continue
            chosen = reserve
            break

        if chosen is None:
            _blacklist_target(session, campaign_id, target_id, reason="reserve exhausted")
            session.commit()
            log.warning(
                "shilling.failover.reserve_exhausted",
                campaign_id=campaign_id, target_id=target_id,
            )
            return None

        # Повышаем резерв в основной состав на роль выбывшего, выбывшего снимаем.
        chosen.is_reserve = False
        chosen.role_id = role_id
        link_repo.detach(campaign_id, failed_account_id)
        session.commit()
        new_account_id = chosen.account_id

    await task_queue.enqueue(
        TaskName.SHILLING_EXECUTE_STEP,
        campaign_id,
        target_id,
        step_id,
        new_account_id,
        thread_msg_id=thread_msg_id,
    )
    log.info(
        "shilling.failover.replaced",
        campaign_id=campaign_id,
        failed_account_id=failed_account_id,
        new_account_id=new_account_id,
        role_id=role_id,
    )
    return new_account_id


def _blacklist_target(session, campaign_id: int, target_id: int, *, reason: str) -> None:
    """Добавляет цель в ЧС кампании (auto=True). Идемпотентно."""
    target = CampaignTargetRepository(session).get(target_id)
    if target is None:
        return
    bl_repo = BlacklistRepository(session)
    chat_id = target.resolved_chat_id
    username = target.raw_input if target.kind == "username" else None
    if chat_id is None and not username:
        return  # нечего заносить (BlacklistCreate требует идентификатор)
    if bl_repo.is_blacklisted(campaign_id, chat_id=chat_id, username=username):
        return
    bl_repo.create(
        campaign_id,
        BlacklistCreate(chat_id=chat_id, username=username, reason=reason),
        auto=True,
    )
