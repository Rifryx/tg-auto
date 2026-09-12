"""Реестр действий прогрева (PROJECT-STAGES §3).

Каждый ``action_type`` реализован отдельным модулем с публичным
``async execute(client, account) -> WarmingActionResult``. Реальные вызовы
Telethon обёрнуты в try/except (см. :func:`worker.warming.actions.base.action`).
"""

from __future__ import annotations

from core.enums import WarmingActionType
from core.models import Account
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


async def execute_action(
    action_type: WarmingActionType, client, account: Account
) -> WarmingActionResult:
    """Выполняет действие данного типа над клиентом аккаунта."""
    return await ACTIONS[action_type](client, account)


__all__ = ["ACTIONS", "WarmingActionResult", "execute_action"]
