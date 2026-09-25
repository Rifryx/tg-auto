"""Оркестратор кампании шиллинга (docs/neuroshilling-spec.md § 5.2, 5.3).

Пока реализован ``failover`` (промпт 4.3) — замена забаненного аккаунта на
резервный той же роли. ``start_campaign`` / ``process_target`` — промпт 4.4.

Инъекции через ctx: session_factory, task_queue, now, rng, publisher.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Optional

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
)
from modules.shilling.schemas import BlacklistCreate

get_logger = structlog.get_logger

_USABLE_ACCOUNT_STATUSES = {"pool", "assigned"}


def _task_queue(ctx: dict) -> TaskQueue:
    return ctx.get("task_queue") or TaskQueue(redis=ctx.get("redis"))


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
