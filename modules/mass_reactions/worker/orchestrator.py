"""Раскладчик пар чат/аккаунт для масс-реакций (spec §4).

Пока — чистая логика назначения + применение через репозитории. Полный tick с
reschedule и подключением слушателей — на финальном интеграционном шаге.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from core.config.priming_warmup import effective_daily_limit
from modules.mass_reactions.models import MassReactionCampaign
from modules.mass_reactions.repositories import (
    CampaignAccountRepository,
    CampaignChatRepository,
)


def plan_chat_assignments(
    unassigned_chat_ids: list[int],
    account_slots: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Round-robin раскладка чатов по аккаунтам с учётом свободных слотов.

    ``account_slots`` — список ``(account_id, free_slots)`` (сколько ещё чатов
    можно закрепить за аккаунтом, ``max_chats_per_account - уже_закреплено``).
    Возвращает список ``(chat_id, account_id)``; чаты, которым не хватило
    слотов, в результат не попадают (ждут следующего tick / новых аккаунтов).
    """
    slots = {aid: max(0, free) for aid, free in account_slots}
    # Порядок аккаунтов фиксируем по исходному списку (детерминированно).
    order = [aid for aid, _ in account_slots]
    out: list[tuple[int, int]] = []
    for chat_id in unassigned_chat_ids:
        # Берём аккаунт с наибольшим числом свободных слотов (баланс нагрузки).
        candidate: Optional[int] = None
        for aid in order:
            if slots.get(aid, 0) <= 0:
                continue
            if candidate is None or slots[aid] > slots[candidate]:
                candidate = aid
        if candidate is None:
            break  # мест больше нет — остальные чаты ждут
        out.append((chat_id, candidate))
        slots[candidate] -= 1
    return out


def account_daily_cap(campaign: MassReactionCampaign, account) -> int:
    """Фактический дневной лимит реакций аккаунта с учётом warmup-рампы,
    ограниченный кампанийским cap (переиспользуем конфиг прайминга)."""
    return effective_daily_limit(
        campaign.warmup_profile,
        getattr(account, "warmup_started_at", None),
        campaign_cap=campaign.daily_limit_per_account,
    )


def assign_pending_chats(session: Session, campaign: MassReactionCampaign) -> int:
    """Закрепляет неназначенные чаты кампании за доступными аккаунтами.

    Возвращает число назначенных чатов. Соблюдает лимит
    ``max_chats_per_account``.
    """
    chats = CampaignChatRepository(session)
    accounts = CampaignAccountRepository(session)

    unassigned = [c.id for c in chats.list_unassigned(campaign.id)]
    if not unassigned:
        return 0

    used = chats.count_by_account(campaign.id)
    cap = campaign.max_chats_per_account
    slots = [
        (a.account_id, cap - used.get(a.account_id, 0))
        for a in accounts.list_available(campaign.id)
    ]
    plan = plan_chat_assignments(unassigned, slots)
    for chat_id, account_id in plan:
        chats.assign_account(chat_id, account_id)
    return len(plan)
