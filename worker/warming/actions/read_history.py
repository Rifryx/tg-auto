"""«Чтение» истории канала: подтянуть сообщения и продвинуть read-статус."""

from __future__ import annotations

import random

from core.enums import WarmingActionType
from core.models import Account
from worker.warming.actions.base import DISCOVERY_CHANNELS, action


@action(WarmingActionType.READ_HISTORY)
async def execute(client, account: Account):
    target = random.choice(DISCOVERY_CHANNELS)
    await client.get_messages(target, limit=random.randint(10, 30))
    await client.send_read_acknowledge(target)
    return target
