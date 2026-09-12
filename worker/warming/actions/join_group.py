"""Вступление в публичную группу (действие прогрева)."""

from __future__ import annotations

import random

from core.enums import WarmingActionType
from core.models import Account
from worker.warming.actions.base import DISCOVERY_GROUPS, action


@action(WarmingActionType.JOIN_GROUP)
async def execute(client, account: Account):
    from telethon.tl.functions.channels import JoinChannelRequest

    target = random.choice(DISCOVERY_GROUPS)
    await client(JoinChannelRequest(target))
    return target
