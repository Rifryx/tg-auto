"""«Просмотр» медиа: подтянуть последние сообщения канала с медиа."""

from __future__ import annotations

import random

from core.enums import WarmingActionType
from core.models import Account
from worker.warming.actions.base import DISCOVERY_CHANNELS, action


@action(WarmingActionType.VIEW_MEDIA)
async def execute(client, account: Account):
    target = random.choice(DISCOVERY_CHANNELS)
    await client.get_messages(target, limit=random.randint(5, 15))
    return target
