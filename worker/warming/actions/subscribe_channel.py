"""Подписка на публичный канал (действие прогрева)."""

from __future__ import annotations

import random

from core.enums import WarmingActionType
from core.models import Account
from worker.warming.actions.base import DISCOVERY_CHANNELS, action


@action(WarmingActionType.SUBSCRIBE_CHANNEL)
async def execute(client, account: Account):
    from telethon.tl.functions.channels import JoinChannelRequest

    target = random.choice(DISCOVERY_CHANNELS)
    await client(JoinChannelRequest(target))
    return target
