"""Побыть онлайн в разумном окне (без активных действий)."""

from __future__ import annotations

from core.enums import WarmingActionType
from core.models import Account
from worker.warming.actions.base import action


@action(WarmingActionType.IDLE_ONLINE)
async def execute(client, account: Account):
    from telethon.tl.functions.account import UpdateStatusRequest

    await client(UpdateStatusRequest(offline=False))
    return None
