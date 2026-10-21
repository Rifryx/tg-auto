"""«Просмотр» медиа: подтянуть последние сообщения канала с медиа."""

from __future__ import annotations

import random
from typing import Optional

from core.enums import WarmingActionType
from core.models import Account, Persona
from worker.warming.actions.base import DISCOVERY_CHANNELS, action, pick_target


@action(WarmingActionType.VIEW_MEDIA)
async def execute(
    client,
    account: Account,
    *,
    persona: Optional[Persona] = None,
    rng: Optional[random.Random] = None,
    **_: object,
):
    rng = rng or random.Random()
    target = pick_target(rng, persona, "channel", DISCOVERY_CHANNELS)
    count = rng.randint(5, 15)
    messages = await client.get_messages(target, limit=count)
    viewed = len(messages) if messages is not None else count
    # meta: где (target) и сколько сообщений «просмотрено».
    return target, {"viewed": int(viewed)}
