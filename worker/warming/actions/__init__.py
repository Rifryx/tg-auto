"""Реестр действий прогрева (PROJECT-STAGES §3).

Каждый ``action_type`` реализован отдельным модулем с публичным
``async execute(client, account, *, persona=None, rng=None) -> WarmingActionResult``.
Реальные вызовы Telethon обёрнуты в try/except (см.
:func:`worker.warming.actions.base.action`), а таргеты выбираются через
:func:`worker.warming.actions.base.pick_target` (persona.interests → fallback).
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any, Callable, Optional

from core.enums import WarmingActionType, WarmingActivityStatus
from core.models import Account, Persona
from worker.warming.actions import (
    idle_online,
    join_group,
    reaction,
    read_history,
    subscribe_channel,
    update_profile,
    view_media,
)
from worker.warming.actions.base import WarmingActionResult

ACTIONS = {
    WarmingActionType.SUBSCRIBE_CHANNEL: subscribe_channel.execute,
    WarmingActionType.READ_HISTORY: read_history.execute,
    WarmingActionType.REACTION: reaction.execute,
    WarmingActionType.VIEW_MEDIA: view_media.execute,
    WarmingActionType.JOIN_GROUP: join_group.execute,
    WarmingActionType.IDLE_ONLINE: idle_online.execute,
    WarmingActionType.UPDATE_PROFILE: update_profile.execute,
}

# action_type для лимитера прогрева (см. worker/health/governor.py::LIMITS).
_WARMING_ACTION = "warming"


async def execute_action(
    action_type: WarmingActionType,
    client,
    account: Account,
    *,
    governor: Any = None,
    session_factory: Optional[Callable[[], Any]] = None,
    publisher: Any = None,
    now: Optional[datetime] = None,
    persona: Optional[Persona] = None,
    rng: Optional[random.Random] = None,
) -> WarmingActionResult:
    """Выполняет действие данного типа над клиентом аккаунта.

    Перед реальным вызовом — резерв слота в governor (лимит ``warming``): если
    исчерпан, действие НЕ выполняется и возвращается ``status=skipped``
    (``reason=rate_limited``) — это не ошибка прогрева, клиент не трогается
    (аудит #7). Сам вызов Telethon внутри действия обёрнут в
    ``around_telethon_call`` (health-события, аудит #8).

    ``persona`` и ``rng`` пробрасываются в action-тела для persona-based
    выбора таргета (этап 10, backlog #1).
    """
    if governor is not None and not await governor.check_and_reserve(
        account.id, _WARMING_ACTION
    ):
        return WarmingActionResult(
            action_type,
            WarmingActivityStatus.SKIPPED,
            meta={"reason": "rate_limited"},
        )
    return await ACTIONS[action_type](
        client,
        account,
        session_factory=session_factory,
        publisher=publisher,
        now=now,
        persona=persona,
        rng=rng,
    )


__all__ = ["ACTIONS", "WarmingActionResult", "execute_action"]
